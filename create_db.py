import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()
client = MongoClient(os.getenv('MONGODB_URL'))

db = client['mvpbot']

db.channels.insert_one({'_name': 'subscribed_channels', '_subscribed_channels': []})