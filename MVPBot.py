import logging
import os
from datetime import datetime, timedelta

from discord import Embed, HTTPException
from discord.ext import commands
from dotenv import load_dotenv

from google_sheets import get_sheet_data

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
    for mvp_row in mvp_sheet[2:]:
        new_time = datetime.strptime(mvp_row[5], "%H:%M %p").time()
        new_datetime = datetime.combine(filter_date.date(), new_time)
        if new_datetime >= filter_date and mvp_row[3]:
            filtered_sheet.append(mvp_row)
    return filtered_sheet


def get_tables():
    current_date = datetime.utcnow()
    trigger_date = datetime.utcnow().replace(hour=21, minute=0, second=0)
    tomorrow = None
    if current_date >= trigger_date:
        tomorrow = current_date + timedelta(days=1)


def build_embed_from_sheet(sheet):
    sheet_embed = Embed(title=f'Upcoming MVPS - {datetime.utcnow().strftime("%D %I:%H %p")} UTC')
    for line in sheet:
        sheet_embed.add_field(name=f'{line[5]} UTC - {line[6]} PST - {line[7]} CEST - {line[9]} AEST', value=f'Location: {line[3]}', inline=False)
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
async def update_prefix(ctx):
    table = get_sheet_data('9/4/20!A:M')
    await ctx.send(embed=build_embed_from_sheet(table))


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
