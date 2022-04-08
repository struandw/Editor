import karelia
import time
import json
import sys
import sqlite3
import pprint

def startswith(string, prefixes):
    for prefix in prefixes:
        if string.startswith(prefix):
            return True
    return False

editbot = karelia.bot("Editor", "xkcd")
editbot.stock_responses["short_help"] = "s/fix/typos"
editbot.stock_responses["long_help"] = """Use me to edit your messages and fix your typos. Evidence of your change will be public. 

Make a child message to your message, with the syntax !edit wrong->write, where wrong is the original text and right is the correction.

[Pouncy Silverkitten] This example message has a typos.
    [Pouncy Silverkitten] !edit typos->typo

This example will become:

[Pouncy Silverkitten] This example message has a typo.

You may also use !optin @Editor to enable the optional sed syntax, and !optout @Editor to disable it.

As you may have inferred, this bot was built by @PouncySilverkitten and forms part of the Karelian Legion.
"""

conn = sqlite3.connect("edits.db")
c = conn.cursor()

c.execute("CREATE TABLE IF NOT EXISTS sed_optin (id TEXT)")
conn.commit()

editbot.connect()

with open("creds.json", "r") as f:
    creds = json.loads(f.read())

login_command = {
    "type": "login",
    "data": {
        "namespace": "email",
        "id": creds["id"],
        "password": creds["password"]
    }
}

edit_command = {
    "type": "edit-message",
    "data": {
        "id": "07dte1vvdxkow",
        "previous_edit_id": "",
        "content": "",
        "delete": False,
        "announce": True,
    }
}

request_parent_command = {
    "type": "get-message",
    "data": {
        "id": "",
    }
}

if not editbot.logged_in:
    editbot.send(login_command)

backoff = 1

while True:
    message = editbot.parse()
    use_sed = False

    if message.type == "send-event":
        if hasattr(message.data, "parent") and startswith(message.data.content, ["!edit ", "s/"]):
            if message.data.content.startswith("s/"):
                use_sed = True
                c.execute("""SELECT * FROM sed_optin WHERE id = ?;""", (message.data.sender.id,))
                result = c.fetchone()
                if not result or result == 0:
                    continue

            edit_requester = message.data.sender.id
            edit_requested_on = message.data.parent
            requested_edit = message.data.content[2:].split("/") if use_sed else message.data.content[6:].split("->")
            request_parent_command["data"]["id"] = edit_requested_on
            editbot.send(request_parent_command)
            while message.type != "get-message-reply":
                message = editbot.parse()

            if message.data.sender.id == edit_requester:
                edit_command['data']["id"] = edit_requested_on
                if hasattr(message.data, "previous_edit_id"):
                    edit_command["data"]["previous_edit_id"] = message.data.previous_edit_id
                edit_command["data"]["content"] = message.data.content.replace(requested_edit[0], requested_edit[1])
                edit_command["data"]["delete"] = False
                editbot.send(edit_command)

        if message.data.content == "!optin @Editor":
            c.execute("""INSERT OR IGNORE INTO sed_optin VALUES (?)""", (message.data.sender.id,))
            conn.commit()
            editbot.reply("You can now use sed syntax.kill ")

        elif message.data.content == "!optout @Editor":
            c.execute("""DELETE FROM sed_optin WHERE id = ?""", (message.data.sender.id,))
            conn.commit()
            editbot.reply("You will no longer be able to use the sed syntax.")

    elif message.type == "login-reply" and message.data.success:
        editbot.logged_in = True
        editbot.disconnect()
        editbot.connect()
