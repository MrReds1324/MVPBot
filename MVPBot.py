import logging
import os
from datetime import datetime, timedelta

from discord import Embed, HTTPException
from discord.ext import commands
from dotenv import load_dotenv

from google_sheets import get_sheet_data, create_sheet, copy_paste, get_sheetid

load_dotenv()
logger = logging.getLogger('discord')
logger.setLevel(os.getenv('LOGGING_LEVEL'))
handler = logging.FileHandler(filename='err.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

token = os.getenv('DISCORD_TOKEN')
spreadsheet_id = os.getenv('SPREADSHEET_ID')

bot = commands.Bot(command_prefix='!!')


def filter_sheet(filter_date, mvp_sheet):
    filtered_sheet = []
    if len(mvp_sheet) >= 2:
        for mvp_row in mvp_sheet[2:]:
            new_time = datetime.strptime(mvp_row[5], "%I:%M %p").time()
            new_datetime = datetime.combine(filter_date.date(), new_time)
            if new_datetime >= filter_date and mvp_row[3]:
                filtered_sheet.append(mvp_row)
    return filtered_sheet


def get_todays_sheet():
    current_date = datetime.utcnow()
    return filter_sheet(current_date, get_sheet_data(f'{current_date.strftime("%D")}!A:M', spreadsheet_id))


def get_tomorrows_sheet():
    tomorrow_date = datetime.utcnow().replace(hour=0, minute=0, second=0) + timedelta(days=1)
    return filter_sheet(tomorrow_date, get_sheet_data(f'{tomorrow_date.strftime("%D")}!A:M', spreadsheet_id))


def get_both_sheets():
    tomorrow_date = datetime.utcnow().replace(hour=0, minute=0, second=0) + timedelta(days=1)
    current = get_todays_sheet()
    current.append([tomorrow_date.strftime('%D %I:%H %p')])
    tomorrow = get_tomorrows_sheet()
    current.extend(tomorrow)
    return current


def build_tomorrow_sheet():
    tomorrow_date = datetime.utcnow().replace(hour=0, minute=0, second=0) + timedelta(days=1)
    if create_sheet(tomorrow_date.strftime('%D'), spreadsheet_id):
        copy_from_id = get_sheetid('Copy Me!', spreadsheet_id)
        copy_to_id = get_sheetid(tomorrow_date.strftime('%D'), spreadsheet_id)
        copy_paste(copy_from_id, copy_to_id, spreadsheet_id)


def build_embed_from_sheet(date_time, sheet):
    sheet_embed = Embed(title=f'Upcoming MVPS - {date_time.strftime("%D %I:%H %p")} UTC')
    for line in sheet:
        if len(line) > 1:
            sheet_embed.add_field(name=f'{line[5]} UTC - {line[6]} PST - {line[7]} CEST - {line[9]} AEST', value=f'Location: {line[3]}', inline=False)
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


@bot.command(name='mvp', help='Show the current MVP list')
async def get_mvp(ctx):
    table = get_both_sheets()
    await ctx.send(embed=build_embed_from_sheet(datetime.utcnow(), table))


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


bot.run(token)
