import json
import logging
import sqlite3
import sys
from queue import Queue
from threading import Thread

import karelia


class Editor:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        handler = logging.FileHandler('editor.log')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        sys.excepthook = self.handle_exception

        self.ROOM = sys.argv[1]

        self.q = Queue()
        self.editbot = Thread(target = self.main)
        self.host_bot = Thread(target = self.host_thread)
        self.editbot.start()
        self.host_bot.start()

    def handle_exception(self, exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        
        self.logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


    def keepalive(self):
        while True:
            self.host_bot.parse()

    def host_thread(self):
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

        self.host_bot = karelia.bot(["EditorBot"], self.ROOM, renegade=True)
        self.host_bot.cookie = ""
        self.host_bot.connect()

        if not self.host_bot.logged_in:
            self.logger.debug("Logging in...")
            self.host_bot.send(login_command)
            self.logger.debug("Awaiting login response...")
            while True:
                message = self.host_bot.parse()
                self.logger.debug(f"    {message.type}")
                if message.type == "login-reply" and message.data.success:
                    break
        
        self.logger.debug("Received login-reply, disconnecting...")
        self.host_bot.logged_in = True
        self.host_bot.disconnect()
        self.host_bot.connect(stealth=True)
        self.logger.debug("Reconnected!")

        keepalive_thread = Thread(target=self.keepalive)
        keepalive_thread.start()

        while True:
            if self.q.qsize():
                packet = self.q.get()
                self.logger.debug(f"[{self.message.data.id}] Host thread received packet.")
                self.host_bot.send(packet)
                self.logger.debug(f"[{self.message.data.id}] Host thread sent packet.")

    def startswith(self, string, prefixes):
        for prefix in prefixes:
            if string.startswith(prefix):
                return True
        return False

    def sed(self, command, string, sep="/"):
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

    def edit(self, command, string):
        if ("->") in command:
            edit_from, edit_to = command.split("->", 1)
            print(edit_from, edit_to)
            string = string.replace(edit_from, edit_to)
        
        return string

    def is_valid_sed_command(self, command):
        if command.startswith("s") and len(command) > 1 and not command[1].isalnum():
            return True
        return False

    def main(self):
        self.editbot = karelia.bot("Editor", self.ROOM)
        self.editbot.stock_responses["short_help"] = "s/fix/typos"
        self.editbot.stock_responses["long_help"] = """Use me to edit your messages and fix your typos. Evidence of your change will be public. 

        Make a child message to your message, with the syntax !edit wrong->write, where wrong is the original text and right is the correction.

        [Pouncy Silverkitten] This example message has a typos.
            [Pouncy Silverkitten] !edit typos->typo

        This example will become:

        [Pouncy Silverkitten] This example message has a typo.

        You may also use !optin @Editor to enable the optional sed syntax, and !optout @Editor to disable it.

        As you may have inferred, this bot was built by @PouncySilverkitten and forms part of the Karelian Legion.
        """

        self.conn = sqlite3.connect("edits.db")
        self.c = self.conn.cursor()

        self.c.execute("CREATE TABLE IF NOT EXISTS sed_optin (id TEXT )")
        self.conn.commit()

        self.editbot.connect()

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
            self.message = self.editbot.parse()
            use_sed = False

            if self.message.type == "send-event":
                if hasattr(self.message.data, "parent") and (self.message.data.content.startswith("!edit ") or self.is_valid_sed_command(self.message.data.content)):
                    self.logger.debug(f"[{self.message.data.id}] Got an edit request packet")
                    if self.is_valid_sed_command(self.message.data.content):
                        self.logger.debug(f"[{self.message.data.id}] Requested sed")
                        self.c.execute("""SELECT * FROM sed_optin WHERE id = ?;""", (self.message.data.sender.id,))
                        result = self.c.fetchone()
                        if result is not None and result != 0:
                            self.logger.debug(f"[{self.message.data.id}] User has sed enabled")
                            use_sed = True

                    if self.is_valid_sed_command(self.message.data.content) and not use_sed:
                        self.logger.debug(f"[{self.message.data.id}] User does not have have sed disabled")
                        continue

                    edit_requester = self.message.data.sender.id
                    edit_requested_on = self.message.data.parent
                    requested_edit = self.message.data.content[2:] if use_sed else self.message.data.content[6:]
                    edit_delimiter = self.message.data.content[1]
                    request_parent_command["data"]["id"] = edit_requested_on
                    self.editbot.send(request_parent_command)
                    self.logger.debug(f"[{self.message.data.id}] Requested parent message")
                    while self.message.type != "get-message-reply":
                        self.message = self.editbot.parse()

                    if self.message.data.sender.id == edit_requester:
                        self.logger.debug(f"[{self.message.data.id}] Parent message is OK")
                        edit_command['data']["id"] = edit_requested_on
                        if hasattr(self.message.data, "previous_edit_id"):
                            edit_command["data"]["previous_edit_id"] = self.message.data.previous_edit_id

                        try:
                            if use_sed:
                                edit_command["data"]["content"] = self.sed(requested_edit, self.message.data.content, edit_delimiter)
                            else:
                                edit_command["data"]["content"] = self.edit(requested_edit, self.message.data.content)
                            self.logger.debug(f"[{self.message.data.id}] Edited message assembled:\n    {self.message.data.content}\n->  {edit_command['data']['content']}")
                        except Exception as e:
                            self.logger.error(e)
                            continue

                        edit_command["data"]["delete"] = False
                        if edit_command["data"]["content"] != self.message.data.content:
                            self.logger.debug(f"[{self.message.data.id}] Sending edit packet to host thread")
                            self.q.put(edit_command)

                elif self.message.data.content == "!optin @Editor":
                    self.c.execute("""INSERT OR IGNORE INTO sed_optin VALUES (?)""", (self.message.data.sender.id,))
                    self.conn.commit()
                    self.editbot.reply("You can now use sed syntax.")

                elif self.message.data.content == "!optout @Editor":
                    self.c.execute("""DELETE FROM sed_optin WHERE id = ?""", (self.message.data.sender.id,))
                    self.conn.commit()
                    self.editbot.reply("You will no longer be able to use the sed syntax.")

                elif hasattr(self.message.data, "parent") and self.message.data.content == "!delete" and self.message.data.sender.is_manager:
                    request_parent_command["data"]["id"] = self.message.data.parent
                    self.editbot.send(request_parent_command)
                    while self.message.type != "get-message-reply":
                        self.message = self.editbot.parse()

                    delete_command = {
                        "type": "edit-message",
                        "data": {
                            "id": self.message.data.id,
                            "previous_edit_id": self.message.data.previous_edit_id if hasattr(self.message.data, "previous_edit_id") else "",
                            "content": "",
                            "delete": True,
                            "announce": True,
                        }
                    }
                    self.q.put(delete_command)

if __name__ == "__main__":
    bot = Editor()
