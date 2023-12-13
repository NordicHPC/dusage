import sys
import subprocess
from dataclasses import dataclass


@dataclass
class Usage:
    space_used_bytes: int = 0
    space_limit_soft_bytes: int = None
    space_limit_hard_bytes: int = None
    inodes_used: int = 0
    inodes_limit_soft: int = None
    inodes_limit_hard: int = None


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


def extract_beegfs(flag, account, _path):
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
        space_limit_soft_bytes=space_limit_bytes,
        space_limit_hard_bytes=space_limit_bytes,
        inodes_used=inodes_used,
        inodes_limit_soft=inodes_limit,
        inodes_limit_hard=inodes_limit,
    )
