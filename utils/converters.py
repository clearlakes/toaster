from discord.ext import commands

def compare(given_str: str, given_list: list[str]):
    """Autocorrects to the closest matching word."""
    for action in given_list:
        if action == given_str or action.startswith(given_str):
            return action

class ValidMethod(commands.Converter):
    async def convert(self, _, given_str: str):
        return compare(given_str, ["ignore", "quarantine", "kick", "ban"])

class ValidAction(commands.Converter):
    async def convert(self, _, given_str: str):
        return compare(given_str, ["clear", "kick", "ban", "add", "queue"])