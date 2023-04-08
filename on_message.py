import random

async def handle_message(message):
    if message.author.id == 154601435990982656 and random.random() < 0.05:
        await message.channel.send("иди нахуй абасранер")