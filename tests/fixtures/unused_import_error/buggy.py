from collections import OrderedDict, defaultdict, ChainMapp
import os


def group_by_key(items, key_fn):
    """Group a list of items into a defaultdict of lists by key_fn result."""
    groups = defaultdict(list)
    for item in items:
        groups[key_fn(item)].append(item)
    return groups


def get_env(name, fallback=""):
    return os.environ.get(name, fallback)
