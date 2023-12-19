"""
Tool to print disk quota information.

Inspired by dusage (written by Lorand Szentannai).
"""

import sys
import getpass
import os

import colorful as cf
from tabulate import tabulate
import click

from dusage_backend import quota_using_project, quota_using_account, quota_using_path

__version__ = "0.3.0-alpha"


def bytes_to_human(n):
    if n is None:
        return None
    try:
        n = int(n)
        for unit in ["", "KiB", "MiB", "GiB", "TiB", "PiB"]:
            if abs(n) < sys.float_info.min:
                return "0.0 KiB"
            if abs(n) < 1024.0:
                return f"{n:.1f} {unit}"
            n /= 1024.0
    except ValueError:
        return None


def number_grouped(n):
    """
    Prints 1234567 as 1 234 567 to make it easier to read.
    """
    if str(n).isdigit():
        return str("{:,}".format(int(n)).replace(",", " "))
    else:
        return n


def anonymize_output(table, n):
    new_table = []
    for row in table:
        path = row[0]

        # replace all characters except the first n with *
        path = path[:n] + "*" * (len(path) - n)

        new_table.append([path] + row[1:])
    return new_table


def color_by_ratio(used, limit):
    # if both are integers
    if str(used).isdigit() and str(limit).isdigit():
        ratio = float(used) / float(limit)
        if ratio > 0.85:
            return "red"
        if ratio > 0.7:
            return "orange"
    return "white"


def colorize(text, color):
    # calls cf.color(text)
    return getattr(cf, color)(text)


def dont_colorize(text, color):
    return text


@click.command()
@click.option(
    "-u", "--user", help=f"The username to check (default: {getpass.getuser()})."
)
@click.option("-p", "--project", help=f"The allocation project.")
@click.option("-d", "--directory", help=f"The directory/path to check.")
@click.option(
    "--no-colors",
    is_flag=True,
    help="Disable colors.",
)
def main(user, project, directory, no_colors):
    cf.update_palette({"blue": "#2e54ff"})
    cf.update_palette({"green": "#08a91e"})
    cf.update_palette({"orange": "#ff5733"})
    cf.update_palette({"red": "#c70039"})

    if no_colors:
        # redefine the colorize function to do nothing
        colorize.__code__ = dont_colorize.__code__

    # only one of user, project, directory can be specified
    if (user and project) or (user and directory) or (project and directory):
        sys.exit(
            colorize("ERROR: ", "red")
            + "please specify user (-u) or project (-p) or directory (-d) but not several at once"
        )

    if user is None:
        user = getpass.getuser()

    hostname = os.environ.get("DUSAGE_HOSTNAME", "undefined")

    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_file = os.path.join(script_dir, "dusage.cfg")

    if directory:
        quota_info = quota_using_path(config_file, hostname, directory)
    elif project:
        quota_info = quota_using_project(config_file, hostname, project)
    else:
        quota_info = quota_using_account(config_file, hostname, user)

    headers = [
        "path",
        "space used",
        "quota (s)",
        "quota (h)",
        "files",
        "quota (s)",
        "quota (h)",
    ]

    headers_blue = [colorize(h, "blue") for h in headers]
    table = []

    for k, v in quota_info.items():
        color_space = color_by_ratio(v["space_used_bytes"], v["space_soft_limit_bytes"])
        color_inodes = color_by_ratio(v["inodes_used"], v["inodes_soft_limit"])
        l = [
            k,
            colorize(bytes_to_human(v["space_used_bytes"]), color_space),
            bytes_to_human(v["space_soft_limit_bytes"]),
            bytes_to_human(v["space_hard_limit_bytes"]),
            colorize(number_grouped(v["inodes_used"]), color_inodes),
            number_grouped(v["inodes_soft_limit"]),
            number_grouped(v["inodes_hard_limit"]),
        ]
        table.append(l)

    # for creating screenshots
    if os.environ.get("DUSAGE_ANONYMIZE_OUTPUT"):
        table = anonymize_output(table, 14)

    print(f"\ndusage v{__version__}\n")

    print(tabulate(table, headers_blue, tablefmt="simple", stralign="right"))

    print("\nPlease report issues at: https://github.com/NordicHPC/dusage")


if __name__ == "__main__":
    main()
