import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from discord import Embed, HTTPException
from discord.ext import commands, tasks
from dotenv import load_dotenv
from pymongo import MongoClient

from google_sheets import get_sheet_data, create_sheet, copy_paste, get_sheetid
from utilities import MVPGap, MVPTimes, SlotKey

load_dotenv()

# Used to load emojis from a different server for development
is_dev = int(os.getenv('IS_DEV') or 0)
if is_dev:
    from utilities import Emojis_dev as Emojis
else:
    from utilities import Emojis

logger = logging.getLogger('discord')
logger.setLevel(os.getenv('LOGGING_LEVEL'))
handler = logging.FileHandler(filename='err.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

token = os.getenv('MVP_DISCORD_TOKEN')
spreadsheet_anywhere_id = os.getenv('SPREADSHEET_HIGH_LVL_ID')
spreadsheet_mushroom_shrine_id = os.getenv('SPREADSHEET_LOW_LVL_ID')
client = MongoClient(os.getenv('MONGODB_URL'))
db = client.mvpbot
# Default timezones to empty dictionary to be loaded later
timezones = {}

bot = commands.Bot(command_prefix='!!')

col_to_tz = {
    7: 'PST',
    8: 'PDT',
    9: 'CST',
    10: 'CDT',
    11: 'EST',
    12: 'EDT',
    13: 'CEST',
    14: 'CEDT',
    15: 'AEST',
    16: 'AEDT',
}

mvp_gap_size = 2
mvp_gap_delta = timedelta(minutes=mvp_gap_size * 15)


def load_daylight_settings():
    day_light_settings = db.settings.find_one({'name': 'daylight_savings'})
    if day_light_settings:
        return day_light_settings
    day_light_settings = {'name': 'daylight_savings',
                          'pacific': {'offset': 0, 'base': 7},
                          'central': {'offset': 0, 'base': 9},
                          'eastern': {'offset': 0, 'base': 11},
                          'central europe': {'offset': 0, 'base': 13},
                          'australia': {'offset': 0, 'base': 15}
                          }
    db.settings.insert_one(day_light_settings)
    return day_light_settings


def get_timezone_col(timezone):
    time = timezones.get(timezone)
    return time.get('base') + time.get('offset')


def get_tomorrows_date():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)


def filter_sheet(filter_start_date, mvp_sheet, search_slots=0):
    """

    :param filter_start_date: The date that all rows must be past
    :param mvp_sheet: The represntation of the google sheet
    :param search_slots: The number of unfilled mvp slots to find
    :return:
    """
    filtered_sheet = []
    open_mvp_slots = MVPTimes(key=SlotKey.Unscheduled.value)
    next_mvp_time = None
    if len(mvp_sheet) >= 2:
        latest_mvp = filter_start_date
        current_map_ch = MVPTimes()
        current_gap = MVPGap()
        for mvp_row in mvp_sheet[2:]:
            try:
                new_time = datetime.strptime(mvp_row[6], "%I:%M %p").replace(tzinfo=timezone.utc)
                base_time = new_time.timetz()
                new_datetime = datetime.combine(filter_start_date.date(), base_time)
                # Start by only looking at rows past the current date
                if new_datetime >= filter_start_date:
                    if mvp_row[4]:
                        # Calculate the how much longer until the next mvp
                        if not current_map_ch.key and len(filtered_sheet) == 0:
                            next_mvp_time = new_datetime - latest_mvp

                        # Save the latest mvp time to determine gaps
                        latest_mvp = new_datetime

                        # If the gap is large enough to save, add the gap to the sheet and start a new one
                        if current_gap.gap_size >= mvp_gap_size:
                            filtered_sheet.append(current_gap)
                            current_gap = MVPGap()
                        else:
                            current_gap = MVPGap()

                        key_ = f'Ch {mvp_row[4]} {mvp_row[3] if mvp_row[3] else "Mushroom Shrine"}'
                        # Determine if the current row matches the previously determined ones
                        if key_ == current_map_ch.key and current_map_ch.discord == mvp_row[0] and current_map_ch.ign == mvp_row[1]:
                            current_map_ch.add(mvp_row, new_datetime)
                        else:
                            if current_map_ch.key:
                                # Add the set of rows to the sheet and set up the new key
                                filtered_sheet.append(current_map_ch)
                                current_map_ch = MVPTimes()
                            # Setup the new row/MVPTimes
                            current_map_ch.key = key_
                            current_map_ch.discord = mvp_row[0]
                            current_map_ch.ign = mvp_row[1]
                            current_map_ch.add(mvp_row, new_datetime)
                    else:
                        # Determine the gap lengths
                        if not current_gap.start_date:
                            current_gap.start_date = new_datetime
                            current_gap.last_date = new_datetime
                            current_gap.gap_size += 1
                        else:
                            current_gap.last_date = new_datetime
                            current_gap.gap_size += 1

                        # If the gap is large enough to save, add the current mvp set to the sheet and start a new one
                        if current_map_ch.key and current_gap.gap_size >= mvp_gap_size:
                            filtered_sheet.append(current_map_ch)
                            current_map_ch = MVPTimes()

                        # Add the open mvp slots if we are searching for them
                        if len(open_mvp_slots.mvp_times) < search_slots:
                            open_mvp_slots.add(mvp_row, new_datetime)
            except:
                logger.error(f"Error occurred when attempting to filter row {mvp_row}")

        # Add the ending set of mvps if they exist
        if current_map_ch.key:
            filtered_sheet.append(current_map_ch)

    return filtered_sheet, next_mvp_time, [open_mvp_slots]


def get_todays_sheet(spreadsheet_id, search_slots=0):
    """
    :param spreadsheet_id: The id of sheet to get information from
    :param search_slots: The number of unfilled mvp slots to find
    :return:
    """
    current_date = datetime.now(timezone.utc)
    return filter_sheet(current_date, get_sheet_data(f'{current_date.strftime("%D")}!A:Z', spreadsheet_id), search_slots)


def get_tomorrows_sheet(spreadsheet_id, search_slots=0):
    """
    :param spreadsheet_id: The id of sheet to get information from
    :param search_slots: The number of unfilled mvp slots to find
    :return:
    """
    tomorrows_date = get_tomorrows_date()
    return filter_sheet(tomorrows_date, get_sheet_data(f'{tomorrows_date.strftime("%D")}!A:Z', spreadsheet_id), search_slots)


def get_both_sheets(spreadsheet_id, search_slots=0):
    """
    Get today + tomorrows google sheets filtered down
    :param spreadsheet_id: The id of sheet to get information from
    :param search_slots: The number of unfilled mvp slots to find
    :return:
    """
    # If we are getting both sheets, then we are in the reset period so pass in true to todays sheet
    current_sheet, next_mvp_time, open_slots = get_todays_sheet(spreadsheet_id, search_slots)

    # Calculate the number of slots to search for
    search_slots = search_slots - len(open_slots) if len(open_slots) < search_slots else 0

    # Add the reset time split for mvps as well as open slots
    reset_mvp_time = MVPTimes(SlotKey.Reset.value, get_tomorrows_date())
    current_sheet.append(reset_mvp_time)
    open_slots.append(reset_mvp_time)

    # Get the mvp sheet and open slots for the next day if needed
    next_sheet, reset_mvp_time, next_open_slots = get_tomorrows_sheet(spreadsheet_id, search_slots)
    current_sheet.extend(next_sheet)
    open_slots.extend(next_open_slots)

    # Determine time to next mvp around across reset boundary which is
    # Time between now and reset + the time between reset and the next mvp
    if not next_mvp_time and reset_mvp_time:
        next_mvp_time = (get_tomorrows_date() - datetime.now(timezone.utc)) + reset_mvp_time

    return current_sheet, next_mvp_time, open_slots


def build_tomorrow_sheet(spreadsheet_id):
    tomorrow_date = get_tomorrows_date()
    if create_sheet(tomorrow_date.strftime('%D'), spreadsheet_id):
        copy_from_id = get_sheetid('Copy Me!', spreadsheet_id)
        copy_to_id = get_sheetid(tomorrow_date.strftime('%D'), spreadsheet_id)
        copy_paste(copy_from_id, copy_to_id, spreadsheet_id)


def build_mvp_embed(date_time, spreadsheet_id, sheet_embed=None):
    next_day_trigger = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0)

    if date_time >= next_day_trigger:
        # If the sheet does not exist yet - build it
        if not get_sheetid(get_tomorrows_date().strftime('%D'), spreadsheet_id):
            build_tomorrow_sheet(spreadsheet_id)

        sheet, next_mvp_time, open_slots = get_both_sheets(spreadsheet_id)
    else:
        sheet, next_mvp_time, open_slots = get_todays_sheet(spreadsheet_id)

    # Added check to mvp time that it is not None as well as the top_value of the embed
    if next_mvp_time:
        next_mvp_parts = str(next_mvp_time).split(':')
    else:
        next_mvp_parts = ['--', '--']

    # This find the first ch/map combo in the list that isn't reset and makes it as the announcement
    for slot in sheet:
        if slot.key not in (SlotKey.Reset.value, SlotKey.Unscheduled.value):
            top_value = f'{Emojis.Next.value} Next MVP at **{slot.key}** in {next_mvp_parts[0]} hours, {next_mvp_parts[1]} minutes'
            break
    else:
        top_value = f'{Emojis.Stopped.value} Next MVP at -- in -- hours, -- minutes'

    if spreadsheet_id == spreadsheet_anywhere_id:
        level_text = 'Anywhere'
    else:
        level_text = 'Mushroom Shrine'

    # Create a new embed, else continue adding to the current one
    if not sheet_embed:
        sheet_embed = Embed(title=f'Upcoming MVPs • <t:{int(date_time.timestamp())}> Local Time')

    sheet_embed.add_field(name=f'• • • {level_text} MVPs • • •', value=top_value, inline=False)

    first_set = False
    for slot in sheet:
        if SlotKey.Reset.value == slot.key:
            sheet_embed.add_field(name='Server Reset', value=f'<t:{int(slot.single_time.timestamp())}:t> Local Time',  inline=False)

        elif SlotKey.Unscheduled.value == slot.key:
            sheet_embed.add_field(name='Unscheduled', value=f'<t:{int(slot.start_date.timestamp())}:t> -- <t:{int(slot.last_date.timestamp())}:t> Local Time',
                                  inline=False)
        else:
            embed_value = ''
            for mvp_time in slot.mvp_times:
                if not first_set:
                    first_set = True
                    emoji = Emojis.Next.value
                else:
                    emoji = Emojis.Scheduled.value
                embed_value += f'{emoji} <t:{int(mvp_time["dt"].timestamp())}:t> Local Time\n'
            sheet_embed.add_field(name=f'{slot.key} • {"IGN: " + slot.ign + " • " if slot.ign else ""}{"Discord: " + slot.discord if slot.discord else ""}',
                                  value=embed_value, inline=False)
    return sheet_embed


def build_mvp_embed_deprecated(date_time, spreadsheet_id, sheet_embed=None):
    next_day_trigger = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0)

    if date_time >= next_day_trigger:
        # If the sheet does not exist yet - build it
        if not get_sheetid(get_tomorrows_date().strftime('%D'), spreadsheet_id):
            build_tomorrow_sheet(spreadsheet_id)

        sheet, next_mvp_time, open_slots = get_both_sheets(spreadsheet_id)
    else:
        sheet, next_mvp_time, open_slots = get_todays_sheet(spreadsheet_id)

    # Added check to mvp time that it is not None as well as the top_value of the embed
    if next_mvp_time:
        next_mvp_parts = str(next_mvp_time).split(':')
    else:
        next_mvp_parts = ['--', '--']

    # This find the first ch/map combo in the list that isn't reset and makes it as the announcement
    for slot in sheet:
        if slot.key not in (SlotKey.Reset.value, SlotKey.Unscheduled.value):
            top_value = f'{Emojis.Next.value} Next MVP at **{slot.key}** in {next_mvp_parts[0]} hours, {next_mvp_parts[1]} minutes'
            break
    else:
        top_value = f'{Emojis.Stopped.value} Next MVP at -- in -- hours, -- minutes'

    if spreadsheet_id == spreadsheet_anywhere_id:
        level_text = 'Anywhere'
    else:
        level_text = 'Mushroom Shrine'

    # Create a new embed, else continue adding to the current one
    if not sheet_embed:
        sheet_embed = Embed(title=f'Upcoming MVPs • {date_time.strftime("%D %I:%M %p")} UTC')

    sheet_embed.add_field(name=f'• • • {level_text} MVPs • • •',
                          value=top_value, inline=False)

    pac_col = get_timezone_col('pacific')
    east_col = get_timezone_col('eastern')
    cen_e_col = get_timezone_col('central europe')
    aus_col = get_timezone_col('australia')

    first_set = False
    for slot in sheet:
        if SlotKey.Reset.value == slot.key:
            sheet_embed.add_field(name='Server Reset', value=f'{slot.single_time.strftime("%I:%M %p")}  UTC', inline=False)

        elif SlotKey.Unscheduled.value == slot.key:
            sheet_embed.add_field(name='Unscheduled', value=f'{Emojis.Unscheduled.value} {slot.start_date.strftime("%I:%M %p")} UTC -- '
                                                            f'{slot.last_date.strftime("%I:%M %p")} UTC', inline=False)
        else:
            embed_value = ''
            overflow_value = ''
            for mvp_time in slot.mvp_times:
                if not first_set:
                    first_set = True
                    emoji = Emojis.Next.value
                else:
                    emoji = Emojis.Scheduled.value

                # Determine if the line overflows the maximum allowed characters in an embed field and overflow it onto a new block
                current_line = f'{emoji} {mvp_time["row"][6]} UTC - {mvp_time["row"][pac_col]} {col_to_tz[pac_col]} - {mvp_time["row"][east_col]} {col_to_tz[east_col]} - ' \
                               f'{mvp_time["row"][cen_e_col]} {col_to_tz[cen_e_col]} - {mvp_time["row"][aus_col]} {col_to_tz[aus_col]}\n'
                if len(current_line) + len(embed_value) >= 1024:
                    overflow_value += current_line
                else:
                    embed_value += current_line

            sheet_embed.add_field(name=f'{slot.key} • {"IGN: " + slot.ign + " " if slot.ign else ""}{"Discord: " + slot.discord if slot.discord else ""}',
                                  value=embed_value, inline=False)

            if overflow_value:  # Only show the overflow block if there is a need
                sheet_embed.add_field(name=f'{slot.key} • {"IGN: " + slot.ign + " " if slot.ign else ""}{"Discord: " + slot.discord if slot.discord else ""}',
                                      value=overflow_value, inline=False)

    return sheet_embed


def build_open_slots_embed(date_time, search_slots, spreadsheet_id):
    next_day_trigger = datetime.now(timezone.utc).replace(hour=18, minute=0, second=0)

    if date_time >= next_day_trigger:
        # If the sheet does not exist yet - build it
        if not get_sheetid(get_tomorrows_date().strftime('%D'), spreadsheet_id):
            build_tomorrow_sheet(spreadsheet_id)

        sheet, next_mvp_time, open_slots = get_both_sheets(spreadsheet_id, search_slots)
    else:
        sheet, next_mvp_time, open_slots = get_todays_sheet(spreadsheet_id, search_slots)

    sheet_embed = Embed(title=f'Open MVP Timeslots • <t:{int(date_time.timestamp())}> Local Time',
                        description=f'Showing the next {search_slots} timeslots')

    for slot in open_slots:
        if SlotKey.Reset.value == slot.key:
            sheet_embed.add_field(name='Server Reset', value=f'<t:{int(slot.single_time.timestamp())}:t> Local Time', inline=False)
        else:
            embed_value = ''
            for mvp_time in slot.mvp_times:
                embed_value += f'{Emojis.Unscheduled.value} {mvp_time["dt"].strftime("%I:%M %p")} UTC • <t:{int(mvp_time["dt"].timestamp())}:t> Local Time\n'
            if embed_value:
                sheet_embed.add_field(name=slot.key, value=embed_value, inline=False)

    return sheet_embed


# Specify a special channel that have access to these commands
def channel_check(ctx):
    if ctx.channel.id == 869631771707330600:
        return True
    return False


# guild must be in the whitelist to do commands
def whitelist_check(ctx):
    guild = db.whitelist.find_one({'server_id': str(ctx.channel.guild.id)})
    if guild:
        return True
    return False


@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')


@bot.event
async def on_message(message):
    # Dont track the bots messages or let the bot issue commands
    if message.author == bot.user:
        return

    if message.content.startswith('!!'):
        await bot.process_commands(message)
        return


@bot.command(name='timeslots', help='Show the next X available timeslots for Mushroom Shrine MVPs')
@commands.guild_only()
@commands.check(whitelist_check)
async def get_mushroome_shrine_timeslots(ctx, search_slots=1):
    await ctx.send(embed=build_open_slots_embed(datetime.now(timezone.utc), search_slots, spreadsheet_mushroom_shrine_id))


@bot.command(name='timeslotsa', help='Show the next X available timeslots for Anywhere MVPs')
@commands.guild_only()
@commands.check(whitelist_check)
async def get_anywhere_timeslots(ctx, search_slots=1):
    await ctx.send(embed=build_open_slots_embed(datetime.now(timezone.utc), search_slots, spreadsheet_anywhere_id))


@bot.command(name='mvp', help='Shows the upcoming MVPs')
@commands.guild_only()
@commands.check(whitelist_check)
async def get_mvp(ctx):
    filter_date = datetime.now(timezone.utc)
    embed = build_mvp_embed_deprecated(filter_date, spreadsheet_mushroom_shrine_id)
    embed = build_mvp_embed_deprecated(filter_date, spreadsheet_anywhere_id, embed)
    await ctx.send(embed=embed)


@bot.command(name='mvpa', help='Shows the upcoming Anywhere MVPs')
@commands.guild_only()
@commands.check(whitelist_check)
async def get_anywhere_mvp(ctx):
    await ctx.send(embed=build_mvp_embed_deprecated(datetime.now(timezone.utc), spreadsheet_anywhere_id))


@bot.command(name='mvpms', help='Shows the upcoming Mushroom Shrine MVPs')
@commands.guild_only()
@commands.check(whitelist_check)
async def get_mushroom_shrine_mvp(ctx):
    await ctx.send(embed=build_mvp_embed_deprecated(datetime.now(timezone.utc), spreadsheet_mushroom_shrine_id))


@bot.command(name='register', help='Register a channel for the bot post MVPs to')
@commands.has_permissions(administrator=True)
@commands.guild_only()
@commands.check(whitelist_check)
async def register_channel(ctx):
    subscribed_channel = db.channels.find_one({'channel_id': ctx.channel.id})

    if subscribed_channel:
        await ctx.send("Channel already registered for MVPs")
        return
    registered = db.channels.insert_one({'channel_id': ctx.channel.id})
    db.whitelist.update_one({'server_id': str(ctx.channel.guild.id)}, {'$push': {'registered_chs': registered.inserted_id}})
    await ctx.send("Channel registered for MVPs")


@bot.command(name='unregister', help='Unregister a channel for the bot post MVPs to')
@commands.has_permissions(administrator=True)
@commands.guild_only()
@commands.check(whitelist_check)
async def unregister_channel(ctx):
    # Attempt to remove it from the high level mvps
    subscribed_channel = db.channels.find_one({'channel_id': ctx.channel.id})
    if subscribed_channel:
        db.whitelist.update_one({'server_id': str(ctx.channel.guild.id)}, {'$pull': {'registered_chs': subscribed_channel.get('_id')}})
        db.channels.delete_one({'channel_id': ctx.channel.id})
        await ctx.send("Channel unregistered from MVPs")
        return

    # Attempt to remove it from the low level mvps
    subscribed_channel = db.l_channels.find_one({'channel_id': ctx.channel.id})
    if subscribed_channel:
        db.whitelist.update_one({'server_id': str(ctx.channel.guild.id)}, {'$pull': {'registered_l_chs': subscribed_channel.get('_id')}})
        db.l_channels.delete_one({'channel_id': ctx.channel.id})
        await ctx.send("Channel unregistered from MVPs")
        return

    await ctx.send("No channel to unregister")


@bot.command(name='whitelist_add', help='Register a guild to the bot\'s whitelist - !!whitelist_add <name> <server_id>')
@commands.check(channel_check)
async def whitelist_add(ctx, name, guild_id):
    guild = db.whitelist.find_one({'server_id': guild_id})

    if guild:
        await ctx.send(f"Server with the id '{guild_id}' is already registered")
        return
    db.whitelist.insert_one({'name': name, 'server_id': guild_id, 'registered_chs': []})
    await ctx.send(f"Registered server '{name}' with id '{guild_id}'")


@bot.command(name='whitelist_remove', help='Unregister a guild from the bot\'s whitelist - !!whitelist_remove <server_id>')
@commands.check(channel_check)
async def whitelist_remove(ctx, guild_id):
    # Find the guild and remove their related registered channels before removing their whitelist
    guild = db.whitelist.find_one({'server_id': guild_id})
    if guild:
        # Delete high level mvp chs
        for registered_channel in guild.get('registered_chs', []):
            db.channels.delete_one({'_id': registered_channel})
        # Delete low level mvp chs
        for registered_channel in guild.get('registered_l_chs', []):
            db.channels.delete_one({'_id': registered_channel})
    db.whitelist.delete_one({'server_id': guild_id})
    await ctx.send(f"Server with the id '{guild_id}' unregistered")


@bot.command(name='whitelist_list', help='Show all guilds on the bot\'s whitelist')
@commands.check(channel_check)
async def whitelist_list(ctx):
    formatted_string = ''
    for server_obj in db.whitelist.find():
        formatted_string += f'{server_obj.get("name")} | {server_obj.get("server_id")}\n'
    await ctx.send(formatted_string)


@bot.command(name='daylight_savings', help='Move a timezone forward or backward an hour for daylight savings')
@commands.check(channel_check)
async def daylight_savings(ctx, timezone):
    global timezones
    day_light_settings = load_daylight_settings()
    timezone = timezone.lower()
    if day_light_settings.get(timezone):
        timezone_info = day_light_settings.get(timezone)
        if timezone_info.get('offset') == 0:
            timezone_info['offset'] = 1
            await ctx.send(f'Timezone {timezone} has been updated to plus an hour')
        else:
            timezone_info['offset'] = 0
            await ctx.send(f'Timezone {timezone} has been updated to minus an hour')
        db.settings.update_one({'name': 'daylight_savings'}, {"$set": {timezone: timezone_info}})
        # Update the settings stored as part of the script
        timezones[timezone] = timezone_info
    else:
        await ctx.send(f'No timezone {timezone} exists. Valid timezones are "Pacific", "Central", "Eastern", "Central Europe", "Australia"')


@tasks.loop(minutes=1)
async def scheduled_mvp():
    # Post to all the channels
    print(f'{datetime.now(timezone.utc)} - Posting to all channels')
    subscribed_channels = db.channels.find({})
    filter_date = datetime.now(timezone.utc)
    embed = build_mvp_embed(filter_date, spreadsheet_mushroom_shrine_id)
    embed = build_mvp_embed(filter_date, spreadsheet_anywhere_id, embed)

    for ch_obj in subscribed_channels:
        message_channel = bot.get_channel(ch_obj.get('channel_id'))
        if message_channel:
            try:
                last_message = await message_channel.fetch_message(message_channel.last_message_id)
            except:
                last_message = None
            if last_message and last_message.author == bot.user:
                print(f'Editing message in {ch_obj.get("channel_id")}')
                await last_message.edit(embed=embed)
            else:
                print(f'Sending new message in {ch_obj.get("channel_id")}')
                try:
                    await message_channel.send(embed=embed)
                except:
                    print(f'Failed to send new message in {ch_obj.get("channel_id")}')
    print(f'{datetime.now(timezone.utc)} - Finished posting to all channels')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CheckFailure):
        await ctx.send("¯\_(ツ)_/¯")
    elif isinstance(error, HTTPException):
        ctx.send('Something went wrong!')
    else:
        await ctx.send('An error occurred! Please try again')
        print(error)
        logger.error('{}: MESSAGE: {}'.format(error, ctx.message.content))

# Load the timezones once all the methods are loaded into memory
timezones = load_daylight_settings()
scheduled_mvp.start()
try:
    bot.run(token)
except Exception as e:
    print(f'{datetime.now(timezone.utc)}: {e}', file=sys.stderr)
    sys.exit(-1)
