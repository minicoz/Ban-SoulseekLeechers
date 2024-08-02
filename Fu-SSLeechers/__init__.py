from pynicotine.pluginsystem import BasePlugin
from pynicotine.config import config

class Plugin(BasePlugin):
    PLACEHOLDERS = {
        "%files%": "num_files",
        "%folders%": "num_folders"
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.metasettings = {
            "num_files": {
                "description": "Require users to have a minimum number of shared files:",
                "type": "int", "minimum": 0
            },
            "num_folders": {
                "description": "Require users to have a minimum number of shared folders:",
                "type": "int", "minimum": 1
            },
            "ban_min_bytes": {
                "description": "Minimum total size of shared files to avoid a ban (MB)",
                "type": "int", "minimum": 0
            },
            "ban_block_ip": {
                "description": "When banning a user, also block their IP address (If IP Is Resolved)",
                "type": "bool"
            },
            "ignore_user": {
                "description": "Ignore users who do not meet the sharing requirements",
                "type": "bool"
            },
            "bypass_share_limit_for_buddies": {
                "description": "Allow users in the buddy list to bypass the minimum share limit",
                "type": "bool"
            },
            "open_private_chat": {
                "description": "Open chat tabs when sending private messages to leechers",
                "type": "bool"
            },
            "send_message_to_banned": {
                "description": "Send a message to users who are banned",
                "type": "bool"
            },
            "message": {
                "description": ("Private chat message to send to leechers. Each line is sent as a separate message, "
                                "too many message lines may get you temporarily banned for spam!"),
                "type": "textview"
            },
            "recheck_enabled": {
                "description": "Enable re-checking users after a specified number of files",
                "type": "bool"
            },
            "recheck_interval": {
                "description": "Number of files after which to re-check the user's Shared File",
                "type": "int", "minimum": 0
            },
            "detected_leechers": {
                "description": "Detected leechers",
                "type": "list string"
            },
            "suppress_banned_user_logs": {
                "description": "Suppress log entries for banned users",
                "type": "bool"
            },
            "suppress_ignored_user_logs": {
                "description": "Suppress log entries for ignored users",
                "type": "bool"
            },
            "suppress_ip_ban_logs": {
                "description": "Suppress log entries for IP bans",
                "type": "bool",
            },
            "suppress_all_messages": {
                "description": "Suppress all log messages",
                "type": "bool"
            }
        }

        self.settings = {
            "message": "Please share more files if you wish to download from me again. You are banned until then. Thanks!",
            "open_private_chat": False,
            "num_files": 100,
            "num_folders": 20,
            "ban_min_bytes": 1000,
            "ban_block_ip": False,
            "ignore_user": False,
            "bypass_share_limit_for_buddies": True,
            "send_message_to_banned": False,
            "suppress_banned_user_logs": False,
            "suppress_ignored_user_logs": True,
            "suppress_ip_ban_logs": False,
            "suppress_all_messages": False,
            "detected_leechers": [],
            "recheck_interval": 10,
            "recheck_enabled": True
        }

        self.probed_users = {}
        self.resolved_users = {}
        self.uploaded_files_count = {}
        self.previous_buddies = set()

    def loaded_notification(self):
        min_num_files = self.metasettings["num_files"]["minimum"]
        min_num_folders = self.metasettings["num_folders"]["minimum"]

        self.settings["num_files"] = max(self.settings["num_files"], min_num_files)
        self.settings["num_folders"] = max(self.settings["num_folders"], min_num_folders)

        if not self.settings["suppress_all_messages"]:
            self.log("Users need at least %d files and %d folders.", (self.settings["num_files"], self.settings["num_folders"]))

    def update_buddy_list(self):
        """Update the list of buddies."""
        self.previous_buddies = set(self.core.buddies.users)

    def check_user(self, user, num_files, num_folders):
        self.update_buddy_list()

        if user in self.previous_buddies and self.settings["bypass_share_limit_for_buddies"]:
            if not self.settings["suppress_all_messages"]:
                self.log("Buddy %s bypasses share limit.", user)
            return

        if user not in self.probed_users:
            return

        if self.probed_users[user] == "okay":
            return

        is_accepted = (num_files >= self.settings["num_files"] and num_folders >= self.settings["num_folders"])

        if is_accepted or user in self.previous_buddies:
            if user in self.settings["detected_leechers"]:
                self.settings["detected_leechers"].remove(user)

            self.probed_users[user] = "okay"
            if not self.settings["suppress_all_messages"] and not self.settings["suppress_ignored_user_logs"]:
                self.log("User %s meets criteria: %d files, %d folders.", (user, num_files, num_folders))
            self.core.network_filter.unban_user(user)
            self.core.network_filter.unignore_user(user)
            return

        if not self.probed_users[user].startswith("requesting"):
            return

        if user in self.settings["detected_leechers"]:
            self.probed_users[user] = "processed_leecher"
            return

        if (num_files <= 0 or num_folders <= 0) and self.probed_users[user] != "requesting_shares":
            if not self.settings["suppress_all_messages"]:
                self.log("Requesting shares from %s to verify if there not a Leecher.", user)
            self.probed_users[user] = "requesting_shares"
            self.core.userbrowse.request_user_shares(user)
            return

        if not is_accepted:
            self.probed_users[user] = "pending_leecher"
            if not self.settings["suppress_all_messages"]:
                self.log("Leecher %s: %d files, %d folders. Banned and ignored.", (user, num_files, num_folders))
            
            if self.settings["ignore_user"]:
                self.core.network_filter.ignore_user(user)

            self.ban_user(user)
            if self.settings["ban_block_ip"]:
                self.block_ip(user)
        else:
            if not self.settings["suppress_all_messages"]:
                self.log("User %s is Not a Leecher.", user)

    def upload_queued_notification(self, user, virtual_path, real_path):
        if user in self.probed_users:
            self.uploaded_files_count[user] = self.uploaded_files_count.get(user, 0) + 1

            if self.settings["recheck_enabled"] and self.uploaded_files_count[user] % self.settings["recheck_interval"] == 0:
                stats = self.core.users.watched.get(user)
                if stats is not None and stats.files is not None and stats.folders is not None:
                    self.check_user(user, num_files=stats.files, num_folders=stats.folders)
            return

        self.probed_users[user] = "requesting_stats"
        stats = self.core.users.watched.get(user)

        if stats is None:
            return

        if stats.files is not None and stats.folders is not None:
            self.check_user(user, num_files=stats.files, num_folders=stats.folders)

    def user_stats_notification(self, user, stats):
        self.check_user(user, num_files=stats["files"], num_folders=stats["dirs"])

    def upload_finished_notification(self, user, *_):
        if user not in self.probed_users:
            return

        if self.probed_users[user] != "pending_leecher":
            return

        self.probed_users[user] = "processed_leecher"

        if self.settings["send_message_to_banned"] and self.settings["message"]:
            if not self.settings["suppress_all_messages"]:
                self.log("Sending message to banned user %s", user)
            for line in self.settings["message"].splitlines():
                for placeholder, option_key in self.PLACEHOLDERS.items():
                    line = line.replace(placeholder, str(self.settings[option_key]))
                self.send_private(user, line, show_ui=self.settings["open_private_chat"], switch_page=False)

            if user not in self.settings["detected_leechers"]:
                self.settings["detected_leechers"].append(user)

        self.ban_user(user)
        if self.settings["ban_block_ip"]:
            self.block_ip(user)
        if not self.settings["suppress_all_messages"]:
            self.log("User %s banned.", user)

    def ban_user(self, username=None):
        if username:
            self.core.network_filter.ban_user(username)
            if not self.settings["suppress_all_messages"] and not self.settings["suppress_banned_user_logs"]:
                self.log('Banned user: %s', username)

    def block_ip(self, username=None):
        if username and username in self.resolved_users:
            ip_address = self.resolved_users[username].get("ip_address")
            if ip_address:
                if not self.settings["suppress_all_messages"] and not self.settings["suppress_ip_ban_logs"]:
                    self.log('Blocking IP: %s', ip_address)
                ip_list = config.sections["server"].get("ipblocklist", {})

                if ip_list is None:
                    ip_list = {}

                if ip_address not in ip_list:
                    ip_list[ip_address] = username
                    config.sections["server"]["ipblocklist"] = ip_list
                    config.write_configuration()
                    if not self.settings["suppress_all_messages"] and not self.settings["suppress_ip_ban_logs"]:
                        self.log('Blocked IP: %s', ip_address)
                else:
                    if not self.settings["suppress_all_messages"] and not self.settings["suppress_ip_ban_logs"]:
                        self.log('IP already blocked: %s', ip_address)
            else:
                if not self.settings["suppress_all_messages"] and not self.settings["suppress_ip_ban_logs"]:
                    self.log("No IP found for username: %s", username)
        else:
            if not self.settings["suppress_all_messages"] and not self.settings["suppress_ip_ban_logs"]:
                self.log("Username %s IP address was not resolved", username)

    def user_resolve_notification(self, user, ip_address, port, country):
        if user not in self.resolved_users:
            self.resolved_users[user] = {
                'ip_address': ip_address,
                'port': port,
                'country': country
            }
        elif country and self.resolved_users[user]['country'] != country:
            self.resolved_users[user]['country'] = country

    def send_message(self, username):
        if self.settings["send_message_to_banned"] and self.settings["message"]:
            for line in self.settings["message"].splitlines():
                for placeholder, option_key in self.PLACEHOLDERS.items():
                    line = line.replace(placeholder, str(self.settings[option_key]))
                self.send_private(username, line, show_ui=self.settings["open_private_chat"], switch_page=False)
