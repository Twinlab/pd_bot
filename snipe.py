deleted_messages = {}

async def on_message_delete(message):
    deleted_messages[message.channel.id] = message

async def handle_snipe(ctx):
    message = deleted_messages.get(ctx.channel.id)

    if message is None:
        await ctx.send("Нет удалённых сообщений.")
    else:
        attachments = message.attachments
        if attachments:
            img_url = attachments[0].url
        else:
            img_url = None

        content = f"**Крыса:** {message.author}\n**Сообщение:** {message.content}"
        if img_url:
            content += f"\n{img_url}"
        
        await ctx.send(content)