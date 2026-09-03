# Copyright (c) Metals Development Laboratory.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Utils/settings.py

import json
import os

class Settings:
    def __init__(self):
        self.settings_file = "Data/user_settings.json"
        self.default_settings = {"theme": "dark"}
        self.settings = self.load_settings()

    def load_settings(self):
        if os.path.exists(self.settings_file):
            with open(self.settings_file, "r") as f:
                return json.load(f)
        return self.default_settings

    def save_settings(self):
        with open(self.settings_file, "w") as f:
            json.dump(self.settings, f)

    def get_theme(self):
        return self.settings.get("theme", "dark")

    def set_theme(self, theme):
        self.settings["theme"] = theme
        self.save_settings()