import json

user_links = {}  # Store user links in a dictionary
user_links_file = "user_links.json"

# Save user links to a file
def save_user_links(user_links):
    with open(user_links_file, "w") as f:
        output_data = [{"user": user_id, "links": links} for user_id, links in user_links.items()]
        json.dump(output_data, f, ensure_ascii=False, indent=4)

# Handle the linking of a user's Dota 2 account
async def handle_link(ctx, player_id: int, user_links: dict):
    if ctx.author.id not in user_links:
        user_links[ctx.author.id] = []

    if player_id in user_links[ctx.author.id]:
        await ctx.send(f"Аккаунт Dota 2 с ID {player_id} уже привязан к аккаунту Discord <@{ctx.author.id}>.")
        return

    for user_id, links in user_links.items():
        if player_id in links:
            await ctx.send(f"Аккаунт Dota 2 с ID {player_id} уже привязан к другому аккаунту Discord.")
            return

    user_links[ctx.author.id].append(player_id)
    save_user_links(user_links)
    await ctx.send(f"Аккаунт Dota 2 с ID {player_id} успешно привязан к аккаунту Discord <@{ctx.author.id}>.")

# Handle the unlinking of a user's Dota 2 account
async def handle_unlink(ctx, user_links: dict, player_id=None):
    if player_id:
        if ctx.author.id in user_links and player_id in user_links[ctx.author.id]:
            user_links[ctx.author.id].remove(player_id)
            await ctx.send(f"Аккаунт Dota 2 с ID {player_id} успешно отвязан от аккаунта Discord <@{ctx.author.id}>.")
            save_user_links(user_links)
        else:
            await ctx.send(f"Аккаунт Dota 2 с ID {player_id} не был привязан к аккаунту Discord <@{ctx.author.id}>.")
    else:
        if ctx.author.id in user_links:
            del user_links[ctx.author.id]
            await ctx.send(f"Все аккаунты Dota 2 были успешно отвязаны от аккаунта Discord <@{ctx.author.id}>.")
            save_user_links(user_links)
        else:
            await ctx.send(f"Вы еще не привязали ни одного аккаунта Dota 2 к аккаунту Discord <@{ctx.author.id}>.")

# Show a user's linked Dota 2 accounts
async def handle_links(ctx, user_links):
    if ctx.author.id not in user_links:
        await ctx.send("Вы не привязывали аккаунт Dota 2 к своему аккаунту Discord. Используйте команду `!link PLAYER_ID`, чтобы привязать свой аккаунт.")
        return
    links = user_links[ctx.author.id]
    if not links:
        await ctx.send("Вы не привязали ни одного аккаунта Dota 2 к своему аккаунту Discord.")
        return
    message = "Ваши привязанные аккаунты Dota 2:\n"
    for link in links:
        message += f"{link}\n"
    await ctx.send(message)
