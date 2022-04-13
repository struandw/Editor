import json
import logging
import sqlite3
import sys
from queue import Queue
from threading import Thread

import karelia

ROOM = "timemachine"


class HostCommand:
    def __init__(self):
        pass

logger = logging.getLogger(__name__)
handler = logging.FileHandler('editor.log')
formatter = logging.Formatter('%(asctime)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def handle_exception(exc_type, exc_value, exc_traceback):
    global message
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

def keepalive(bot: karelia.bot):
    while True:
        bot.parse()

def host_thread(in_q: Queue):
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

    host_bot = karelia.bot(["bot: Editor"], ROOM)
    host_bot.cookie = ""
    host_bot.connect()

    if not host_bot.logged_in:
        host_bot.send(login_command)
        while True:
            message = host_bot.parse()
            if message.type == "login-reply" and message.data.success:
                break
             
    host_bot.logged_in = True
    host_bot.disconnect()
    host_bot.connect(stealth=True)

    keepalive_thread = Thread(target=keepalive, args=(host_bot,))
    keepalive_thread.start()

    while True:
        if in_q.qsize():
            packet = in_q.get()
            #print(packet)
            host_bot.send(packet)

def startswith(string, prefixes):
    for prefix in prefixes:
        if string.startswith(prefix):
            return True
    return False

def sed(command, string, sep="/"):
    if command.endswith(f"{sep}g"):
        edit_from, edit_to = command[:-2].split(sep)
        string = string.replace(edit_from, edit_to)
    else:
        if command.endswith(sep):
            edit_from, edit_to = command[:-1].split(sep)
        else:
            edit_from, edit_to = command.split(sep)
        string = string.replace(edit_from, edit_to, 1)

    return string

def edit(command, string):
    if ("->") in command:
        edit_from, edit_to = command.split("->", 1)
        print(edit_from, edit_to)
        string = string.replace(edit_from, edit_to)
    
    return string

def is_valid_sed_command(command):
    if command.startswith("s") and not command[1].isalnum():
        return True
    return False

def main(out_q):
    editbot = karelia.bot("Editor", ROOM)
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

    c.execute("CREATE TABLE IF NOT EXISTS sed_optin (id TEXT )")
    conn.commit()

    editbot.connect()

    with open("creds.json", "r") as f:
        creds = json.loads(f.read())

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

    backoff = 1

    while True:
        message = editbot.parse()
        use_sed = False

        if message.type == "send-event":
            if hasattr(message.data, "parent") and (message.data.content.startswith("!edit ") or is_valid_sed_command(message.data.content)):
                if is_valid_sed_command(message.data.content):
                    c.execute("""SELECT * FROM sed_optin WHERE id = ?;""", (message.data.sender.id,))
                    result = c.fetchone()
                    if result is not None and result != 0:
                        use_sed = True

                if is_valid_sed_command(message.data.content) and not use_sed:
                    continue

                edit_requester = message.data.sender.id
                edit_requested_on = message.data.parent
                requested_edit = message.data.content[2:] if use_sed else message.data.content[6:]
                edit_delimiter = message.data.content[1]
                request_parent_command["data"]["id"] = edit_requested_on
                editbot.send(request_parent_command)
                while message.type != "get-message-reply":
                    message = editbot.parse()

                if message.data.sender.id == edit_requester:
                    edit_command['data']["id"] = edit_requested_on
                    if hasattr(message.data, "previous_edit_id"):
                        edit_command["data"]["previous_edit_id"] = message.data.previous_edit_id

                    try:
                        if use_sed:
                            edit_command["data"]["content"] = sed(requested_edit, message.data.content, edit_delimiter)
                        else:
                            edit_command["data"]["content"] = edit(requested_edit, message.data.content)
                    except Exception as e:
                        logger.error(e)
                        continue

                    edit_command["data"]["delete"] = False
                    if edit_command["data"]["content"] != message.data.content:
                        out_q.put(edit_command)

            elif message.data.content == "!optin @Editor":
                c.execute("""INSERT OR IGNORE INTO sed_optin VALUES (?)""", (message.data.sender.id,))
                conn.commit()
                editbot.reply("You can now use sed syntax.")

            elif message.data.content == "!optout @Editor":
                c.execute("""DELETE FROM sed_optin WHERE id = ?""", (message.data.sender.id,))
                conn.commit()
                editbot.reply("You will no longer be able to use the sed syntax.")

            elif hasattr(message.data, "parent") and message.data.content == "!delete" and message.data.sender.is_manager:
                request_parent_command["data"]["id"] = message.data.parent
                editbot.send(request_parent_command)
                while message.type != "get-message-reply":
                    message = editbot.parse()

                delete_command = {
                    "type": "edit-message",
                    "data": {
                        "id": message.data.id,
                        "previous_edit_id": message.data.previous_edit_id if hasattr(message.data, "previous_edit_id") else "",
                        "content": "",
                        "delete": True,
                        "announce": True,
                    }
                }
                out_q.put(delete_command)

if __name__ == "__main__":
    q = Queue()
    editbot = Thread(target = main, args = (q,))
    host_bot = Thread(target = host_thread, args = (q,))
    editbot.start()
    host_bot.start()
