# Copyright (c) Ali Fethi Erdem.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.
#
# Utils/io_helpers.py

import json
import os

def read_json(file_path):
    """reads a JSON file and returns its content."""
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading JSON file {file_path}: {e}")
        return None

def write_json(data, file_path):
    """writes data to a JSON file."""
    try:
        with open(file_path, 'w') as file:
            json.dump(data, file)
    except IOError as e:
        print(f"Error writing to JSON file {file_path}: {e}")

def read_results_in_chunks(file_path, chunk_size=100):
    """yields data from a JSON file in chunks."""
    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading JSON file {file_path} in chunks: {e}")
        return []

def file_exists(file_path):
    """checks if a file exists."""
    return os.path.exists(file_path)