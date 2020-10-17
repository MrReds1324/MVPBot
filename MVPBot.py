import logging
import os
import sys
from asyncio import sleep
from datetime import datetime, timedelta

from discord import Embed, HTTPException
from discord.ext import commands, tasks
from dotenv import load_dotenv
from pymongo import MongoClient

from google_sheets import get_sheet_data, create_sheet, copy_paste, get_sheetid

load_dotenv()
logger = logging.getLogger('discord')
logger.setLevel(os.getenv('LOGGING_LEVEL'))
handler = logging.FileHandler(filename='err.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

token = os.getenv('MVP_DISCORD_TOKEN')
spreadsheet_id = os.getenv('SPREADSHEET_ID')
client = MongoClient(os.getenv('MONGODB_URL'))
db = client.mvpbot

bot = commands.Bot(command_prefix='!!')


def get_tomorrows_date():
    return datetime.utcnow().replace(hour=0, minute=0, second=0) + timedelta(days=1)


def determine_wait(cur_minute):
    if cur_minute <= 10:
        return 60 * (10 - cur_minute)
    elif cur_minute <= 25:
        return 60 * (25 - cur_minute)
    elif cur_minute <= 40:
        return 60 * (40 - cur_minute)
    elif cur_minute <= 55:
        return 60 * (55 - cur_minute)
    else:
        return 60 * (70 - cur_minute)


def filter_sheet(filter_date, mvp_sheet, reset_period=False):
    filtered_sheet = []
    if len(mvp_sheet) >= 2:
        time_gap = None
        lastest_mvp = filter_date
        for mvp_row in mvp_sheet[2:]:
            try:
                new_time = datetime.strptime(mvp_row[6], "%I:%M %p").time()
                new_datetime = datetime.combine(filter_date.date(), new_time)
                if new_datetime >= filter_date:
                    if mvp_row[4]:
                        if time_gap:
                            filtered_sheet.append(['MVP GAP', time_gap])
                            time_gap = None
                        # Add the row to the sheet
                        filtered_sheet.append(mvp_row)
                        # Save the latest mvp time to determine gaps
                        lastest_mvp = new_datetime
                    else:
                        time_gap = new_datetime - lastest_mvp
            except:
                logger.error(f"Error occured when attempting to filter row {mvp_row}")

        if reset_period and time_gap:
            # Have to add an extra 0.5 to account for the fact that gaps dont start counting until the next time slot
            filtered_sheet.append(['MVP GAP', time_gap])
    return filtered_sheet


def get_todays_sheet(reset_period=False):
    current_date = datetime.utcnow()
    return filter_sheet(current_date, get_sheet_data(f'{current_date.strftime("%D")}!A:Z', spreadsheet_id), reset_period)


def get_tomorrows_sheet():
    tomorrows_date = get_tomorrows_date()
    return filter_sheet(tomorrows_date, get_sheet_data(f'{tomorrows_date.strftime("%D")}!A:Z', spreadsheet_id))


def get_both_sheets():
    # If we are getting both sheets, then we are in the reset period so pass in true to todays sheet
    current = get_todays_sheet(True)
    current.append([get_tomorrows_date().strftime('%D %I:%H %p')])
    current.extend(get_tomorrows_sheet())
    return current


def build_tomorrow_sheet():
    tomorrow_date = get_tomorrows_date()
    if create_sheet(tomorrow_date.strftime('%D'), spreadsheet_id):
        copy_from_id = get_sheetid('Copy Me for xx15/45!', spreadsheet_id)
        copy_to_id = get_sheetid(tomorrow_date.strftime('%D'), spreadsheet_id)
        copy_paste(copy_from_id, copy_to_id, spreadsheet_id)


def build_embed(date_time):
    next_day_trigger = datetime.utcnow().replace(hour=18, minute=0, second=0)

    if date_time >= next_day_trigger:
        # If the sheet does not exist yet - build it
        if not get_sheetid(get_tomorrows_date().strftime('%D'), spreadsheet_id):
            build_tomorrow_sheet()

        sheet = get_both_sheets()
    else:
        sheet = get_todays_sheet()

    sheet_embed = Embed(title=f'Upcoming MVPS - {date_time.strftime("%D %I:%M %p")} UTC')
    for line in sheet:
        if len(line) > 1:
            sheet_embed.add_field(name=f'{line[6]} UTC - {line[7]} PST - {line[9]} EST - {line[10]} CEST - {line[12]} AEST',
                                  value=f'Location: {line[4]}{" --- Teleport To: " + (line[3] or line[1]) if (line[3] or line[1]) else ""}{" --- Discord: " + line[0] if line[0] else ""}',
                                  inline=False)
        else:
            sheet_embed.add_field(name=f'{line[0]} UTC', value="Server Reset", inline=False)
    return sheet_embed


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


@bot.command(name='mvp', help='Show the upcoming mvps')
async def get_mvp(ctx):
    await ctx.send(embed=build_embed(datetime.utcnow()))


@bot.command(name='register', help='Register a channel for the bot post MVPs to')
@commands.has_permissions(administrator=True)
async def register_channel(ctx):
    subscribed_channels = db.channels.find_one({'_name': 'subscribed_channels'})

    if subscribed_channels and subscribed_channels.get('_subscribed_channels'):
        if ctx.channel.id in subscribed_channels.get('_subscribed_channels'):
            await ctx.send("Channel already registered")
            return
    db.channels.update_one({'_name': 'subscribed_channels'}, {'$push': {'_subscribed_channels': ctx.channel.id}})
    await ctx.send("Channel registered")


@bot.command(name='unregister', help='Unregister a channel for the bot post MVPs to')
@commands.has_permissions(administrator=True)
async def unregister_channel(ctx):
    db.channels.update_one({'_name': 'subscribed_channels'}, {'$pull': {'_subscribed_channels': ctx.channel.id}})
    await ctx.send("Channel unregistered")


@tasks.loop(minutes=15)
async def scheduled_mvp():
    # Wait until the appropriate time to post MVPs
    await sleep(determine_wait(datetime.utcnow().minute))

    # Get all the subscribed channels
    subscribed_channels = db.channels.find_one({'_name': 'subscribed_channels'})

    # Post to all the channels
    print(f'{datetime.utcnow()} - Posting to all channels')
    if subscribed_channels and subscribed_channels.get('_subscribed_channels'):
        embed = build_embed(datetime.utcnow())
        for ch in subscribed_channels.get('_subscribed_channels'):
            message_channel = bot.get_channel(ch)
            if message_channel:
                try:
                    last_message = await message_channel.fetch_message(message_channel.last_message_id)
                except:
                    print(f'Failed to get the last message for {ch}')
                    last_message = None
                if last_message and last_message.author == bot.user:
                    print(f'Editing message in {ch}')
                    await last_message.edit(embed=embed)
                else:
                    print(f'Sending new message in {ch}')
                    try:
                        await message_channel.send(embed=embed)
                    except:
                        print(f'Failed to send new message in {ch}')
    print('Finished posting to all channels')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CheckFailure):
        await ctx.send('You do not have the correct role for this command.')
    elif isinstance(error, HTTPException):
        ctx.send('Something went wrong!')
    else:
        await ctx.send('An error occurred! Please try again')
        print(error)
        logger.error('{}: MESSAGE: {}'.format(error, ctx.message.content))


scheduled_mvp.start()
try:
    bot.run(token)
except Exception as e:
    print(f'{datetime.utcnow()}: {e}', file=sys.stderr)
    sys.exit(-1)
