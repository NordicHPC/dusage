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


def bytes_to_human(n):
    for unit in ["", "KiB", "MiB", "GiB", "TiB", "PiB"]:
        if abs(n) < sys.float_info.min:
            return "0.0 KiB"
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return None


def shell_command(command):
    return (
        subprocess.check_output(command, shell=True, stderr=subprocess.DEVNULL)
        .decode("utf-8")
        .strip()
    )


def space_quota(account, flag):
    _, _, space_used, space_limit, inodes_used, inodes_limit = shell_command(
        f"beegfs-ctl --getquota {flag} {account} --csv | grep {account}"
    ).split(",")

    space_used_human = bytes_to_human(int(space_used))

    if space_limit == "unlimited":
        space_limit_human = "-"
        space_ratio = None
    else:
        space_limit_human = bytes_to_human(int(space_limit))
        space_ratio = float(space_used) / float(space_limit)

    if inodes_limit == "unlimited":
        inodes_limit = "-"
        inodes_ratio = None
    else:
        inodes_ratio = float(inodes_used) / float(inodes_limit)

    return (
        space_used_human,
        space_limit_human,
        space_ratio,
        inodes_used,
        inodes_limit,
        inodes_ratio,
    )


def create_row(path, account, flag, csv):
    (
        space_used,
        space_limit,
        space_ratio,
        inodes_used,
        inodes_limit,
        inodes_ratio,
    ) = space_quota(account, flag)
    if space_limit == "-":
        has_backup = "no"
    else:
        if csv:
            has_backup = "yes"
        else:
            has_backup = cf.green("yes")
        if not csv:
            if space_ratio > 0.7:
                space_used = cf.orange(space_used)
            if space_ratio > 0.85:
                space_used = cf.red(space_used)
    if not csv:
        if inodes_ratio is not None:
            if inodes_ratio > 0.5:
                inodes_used = cf.orange(inodes_used)
            if inodes_ratio > 0.8:
                inodes_used = cf.red(inodes_used)
    return [path, has_backup, space_used, space_limit, inodes_used, inodes_limit]


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

    headers = [
        "path",
        "backup",
        "space used",
        "quota",
        "files/folders",
        "quota",
    ]
    headers_blue = list(map(cf.blue, headers))

    table = []
    table.append(create_row(f"/cluster/home/{user}", f"{user}_g", "--gid", csv))
    table.append(create_row(f"/cluster/work/users/{user}", user, "--uid", csv))

    for group in groups(user):
        # for the moment we don't list NIRD information since the quota
        # information is incorrect anyway at the moment
        if not re.match("ns[0-9][0-9][0-9][0-9]k", group.lower()):
            path = f"/cluster/projects/{group}"
            # some groups are not folders but only to control access
            if os.path.isdir(path):
                r = create_row(path, group, "--gid", csv)
                space_used = r[2].strip()
                table.append(r)

    if csv:
        print(",".join(headers))
        for row in table:
            print(",".join(row))
    else:
        print()
        print(tabulate(table, headers_blue, tablefmt="psql", stralign="right"))
        print(
            "\n(*) this script is still being tested, unsure whether the backup information is correct"
        )
        print("    please send suggestions/corrections to radovan.bast@uit.no")


if __name__ == "__main__":
    main()
