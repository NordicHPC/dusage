"""
Tool to print quota information (right now space and number of inodes, later we
could also print compute quotas).

Inspired by dusage (written by Lorand Szentannai).
"""

import subprocess
import colorful as cf
from tabulate import tabulate
import re
import click
import sys
import getpass
import os
import socket

__version__ = "0.1.1"


def bytes_to_human(n):
    for unit in ["", "KiB", "MiB", "GiB", "TiB", "PiB"]:
        if abs(n) < sys.float_info.min:
            return "0.0 KiB"
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return None


def number_grouped(n):
    """
    Prints 1234567 as 1 234 567 to make it easier to read.
    """
    if n.isdigit():
        return str("{:,}".format(int(n)).replace(",", " "))
    else:
        return n


def command_is_available(command) -> bool:
    status, result = subprocess.getstatusoutput(command)
    return "command not found" not in result


def shell_command(command):
    return (
        subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL)
        .decode("utf-8")
        .strip()
    )


def extract_beegfs(flag, account, _path):
    command = f"beegfs-ctl --getquota --{flag}id {account} --csv | grep {account}"
    # 0-th element since we only consider the first pool
    output = shell_command(command).split("\n")[0]
    _, _, space_used, space_limit, inodes_used, inodes_limit = output.split(",")
    if space_limit == "unlimited":
        space_limit = "-"
    if inodes_limit == "unlimited":
        inodes_limit = "-"
    space_limit_soft = space_limit
    inodes_limit_soft = inodes_limit
    return (
        space_used,
        space_limit_soft,
        space_limit,
        inodes_used,
        inodes_limit_soft,
        inodes_limit,
    )


def _extract_lustre_convert(command):
    output = shell_command(command)
    (
        _,
        space_used,
        space_limit_soft,
        space_limit,
        _,
        inodes_used,
        inodes_limit_soft,
        inodes_limit,
        _,
    ) = output.split()
    space_used = space_used.replace("*", "")

    # all numbers are in KiB
    space_used = 1024 * int(space_used)
    if space_limit_soft == "0":
        space_limit_soft = "-"
    else:
        space_limit_soft = 1024 * int(space_limit_soft)
    if space_limit == "0":
        space_limit = "-"
    else:
        space_limit = 1024 * int(space_limit)

    if inodes_limit_soft == "0":
        inodes_limit_soft = "-"
    if inodes_limit == "0":
        inodes_limit = "-"

    return (
        space_used,
        space_limit_soft,
        space_limit,
        inodes_used,
        inodes_limit_soft,
        inodes_limit,
    )


def extract_lustre(flag, account, path):
    command = f"lfs quota -q -{flag} {account} /cluster | grep /cluster"
    return _extract_lustre_convert(command)


def extract_lustre_by_project_id(flag, account, path):
    command = f"lfs quota -q -p $(lfs project -d {path} | awk '{{print $1}}') /cluster"
    return _extract_lustre_convert(command)


def create_row(run_command_and_extract, flag, account, path, csv, show_soft_limits):
    (
        space_used,
        space_limit_soft,
        space_limit,
        inodes_used,
        inodes_limit_soft,
        inodes_limit,
    ) = run_command_and_extract(flag, account, path)

    if space_limit_soft != "-":
        space_limit_soft = bytes_to_human(int(space_limit_soft))

    if space_limit == "-":
        space_ratio = 0.0
    else:
        space_ratio = float(space_used) / float(space_limit)
        space_limit = bytes_to_human(int(space_limit))

    if inodes_limit == "-":
        inodes_ratio = 0.0
    else:
        inodes_ratio = float(inodes_used) / float(inodes_limit)

    space_used = bytes_to_human(int(space_used))

    if space_limit == "-":
        has_backup = "no"
    else:
        if csv:
            has_backup = "yes"
        else:
            has_backup = cf.green("yes")

    if space_limit != "-" and not csv:
        if space_ratio > 0.7:
            space_used = cf.orange(space_used)
        if space_ratio > 0.85:
            space_used = cf.red(space_used)

    if not csv:
        inodes_used = number_grouped(inodes_used)
        if inodes_limit_soft != "-":
            inodes_limit_soft = number_grouped(inodes_limit_soft)
        if inodes_limit != "-":
            inodes_limit = number_grouped(inodes_limit)
            if inodes_ratio > 0.5:
                inodes_used = cf.orange(inodes_used)
            if inodes_ratio > 0.8:
                inodes_used = cf.red(inodes_used)

    if show_soft_limits:
        return [
            path,
            has_backup,
            space_used,
            space_limit_soft,
            space_limit,
            inodes_used,
            inodes_limit_soft,
            inodes_limit,
        ]
    else:
        return [
            path,
            has_backup,
            space_used,
            space_limit,
            inodes_used,
            inodes_limit,
        ]


def row_worth_showing(row):
    inodes_used = row[5]
    return inodes_used != "0"


def groups(account):
    l = shell_command(f"id -Gn {account}").split()
    # removing these two because we treat them separately outside
    l.remove(account)
    l.remove(f"{account}_g")
    return l


user = getpass.getuser()


@click.command()
@click.option(
    "-u", "--user", default=user, help=f"The username to check (default: {user})."
)
@click.option(
    "--csv",
    is_flag=True,
    help="Print information as comma-separated values for parsing by other scripts.",
)
def main(user, csv):
    cf.update_palette({"blue": "#2e54ff"})
    cf.update_palette({"green": "#08a91e"})
    cf.update_palette({"orange": "#ff5733"})

    try:
        _ = shell_command(f"id {user}")
    except:
        sys.exit(cf.red("ERROR: ") + f"user {user} not found")

    skip_user_rows = False
    if command_is_available("beegfs-ctl -h"):
        # this is a beegfs system
        run_command_and_extract = extract_beegfs
        show_soft_limits = False
        headers = [
            "path",
            "backup",
            "space used",
            "quota",
            "files",
            "quota",
        ]
    elif command_is_available("lfs --list-commands"):
        # this is a lustre system
        if "betzy" in socket.gethostname().lower():
            # sorry for this hardcoding
            # please generalize if you know how to
            run_command_and_extract = extract_lustre_by_project_id
            skip_user_rows = True
        else:
            run_command_and_extract = extract_lustre
        show_soft_limits = True
        headers = [
            "path",
            "backup",
            "space used",
            "quota (s)",
            "quota (h)",
            "files",
            "quota (s)",
            "quota (h)",
        ]
    else:
        sys.exit("ERROR: unknown file system")

    headers_blue = list(map(cf.blue, headers))
    table = []

    if not skip_user_rows:
        row = create_row(
            run_command_and_extract,
            "u",
            f"{user}",
            "/cluster",
            csv,
            show_soft_limits,
        )
        if row_worth_showing(row):
            table.append(row)

    row = create_row(
        run_command_and_extract,
        "g",
        f"{user}_g",
        f"/cluster/home/{user}",
        csv,
        show_soft_limits,
    )
    if row_worth_showing(row):
        table.append(row)

    if not skip_user_rows:
        row = create_row(
            run_command_and_extract,
            "g",
            user,
            f"/cluster/work/users/{user}",
            csv,
            show_soft_limits,
        )
        if row_worth_showing(row):
            table.append(row)

    for group in groups(user):
        # for the moment we don't list NIRD information since the quota
        # information is incorrect anyway at the moment
        if not re.match("ns[0-9][0-9][0-9][0-9]k", group.lower()):
            path = f"/cluster/projects/{group}"
            # some groups are not folders but only to control access
            if os.path.isdir(path):
                row = create_row(
                    run_command_and_extract, "g", group, path, csv, show_soft_limits
                )
                if row_worth_showing(row):
                    table.append(row)

    if csv:
        print(",".join(headers))
        for row in table:
            print(",".join(row))
    else:
        print()
        print(f"dusage v{__version__}")
        print(tabulate(table, headers_blue, tablefmt="simple", stralign="right"))
        if show_soft_limits:
            print(
                "\n- quota (s): Soft limit. You can stay above this but only for a while (not sure how long)."
            )
            print(
                "- quota (h): Hard limit. You need to move/remove data/files to be able to write."
            )
        print(
            "\n- This script is still being tested, unsure whether the backup information is correct."
        )
        print("  Please report issues at https://github.com/NordicHPC/dusage.")


if __name__ == "__main__":
    main()
