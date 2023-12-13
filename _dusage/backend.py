import sys
import subprocess
from dataclasses import dataclass
from shutil import which


@dataclass
class Usage:
    space_used_bytes: int = 0
    space_soft_limit_bytes: int = None
    space_hard_limit_bytes: int = None
    inodes_used: int = 0
    inodes_soft_limit: int = None
    inodes_hard_limit: int = None


def shell_command(command):
    try:
        output = (
            subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError as e:
        sys.exit("ERROR: " + e.output.decode("utf-8"))
    return output


def command_is_available(command) -> bool:
    return which(command) is not None


def get_usage_beegfs(flag, account):
    command = f"beegfs-ctl --getquota --{flag}id {account} --csv | grep {account}"

    # 0-th element since we only consider the first pool
    output = shell_command(command).split("\n")[0]

    _, _, space_used_bytes, space_limit_bytes, inodes_used, inodes_limit = output.split(
        ","
    )

    if space_limit_bytes == "unlimited":
        space_limit_bytes = None
    if inodes_limit == "unlimited":
        inodes_limit = None

    return Usage(
        space_used_bytes=space_used_bytes,
        space_soft_limit_bytes=space_limit_bytes,
        space_hard_limit_bytes=space_limit_bytes,
        inodes_used=inodes_used,
        inodes_soft_limit=inodes_limit,
        inodes_hard_limit=inodes_limit,
    )


def collect_groups(account):
    l = shell_command(f"id -Gn {account}").split()

    # removing these two because we treat them separately
    l.remove(account)
    account_g = f"{account}_g"
    if account_g in l:
        l.remove(account_g)

    return l
