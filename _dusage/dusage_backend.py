import sys
import os
import pwd
import subprocess
import configparser
import re
import json


def _stop_with_error(message):
    sys.stderr.write(f"ERROR: {message}\n")
    sys.exit(1)


def _parse_config(file_name, section):
    if not os.path.exists(file_name):
        _stop_with_error(f"could not find configuration file {file_name}")
    config = configparser.ConfigParser()
    config.read(file_name)
    if section not in config.sections():
        _stop_with_error(f"cluster '{section}' not correctly defined in {file_name}")
    return dict(config[section])


def _get_option(config, option):
    if option in config:
        return config[option]
    else:
        _stop_with_error(f"option {option} is not set correctly")


def _shell_command(command):
    try:
        output = (
            subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT)
            .decode("utf-8")
            .strip()
        )
    except subprocess.CalledProcessError as e:
        _stop_with_error(e.output.decode("utf-8"))
    return output


def _parse_beegfs_size(size_str):
    """Parse BeeGFS size string like '190.02GiB' to bytes."""
    size_str = size_str.strip()

    # Extract number and unit
    match = re.match(r'([\d.]+)([A-Za-z]*)', size_str)
    if not match:
        _stop_with_error(f"Cannot parse size: {size_str}")

    value = float(match.group(1))
    unit = match.group(2).upper()

    # Convert to bytes
    multipliers = {
        'B': 1,
        'KIB': 1024,
        'MIB': 1024**2,
        'GIB': 1024**3,
        'TIB': 1024**4,
        'PIB': 1024**5,
    }

    if unit not in multipliers:
        _stop_with_error(f"Unknown size unit: {unit}")

    return int(value * multipliers[unit])


def _parse_beegfs_count(count_str):
    """Parse BeeGFS count string like '836.44k' to integer."""
    count_str = count_str.strip()

    # Extract number and unit
    match = re.match(r'([\d.]+)([A-Za-z]*)', count_str)
    if not match:
        _stop_with_error(f"Cannot parse count: {count_str}")

    value = float(match.group(1))
    unit = match.group(2).upper()

    # Convert to count
    multipliers = {
        '': 1,
        'K': 1000,
        'M': 1000000,
        'G': 1000000000,
    }

    if unit not in multipliers:
        _stop_with_error(f"Unknown count unit: {unit}")

    return int(value * multipliers[unit])


def _beegfs7_quota(option, account, _):
    """Query quota using legacy beegfs-ctl command (BeeGFS 7.x).

    Args:
        option: "u" for user or "g" for group
        account: username or group name

    Returns:
        dict: quota information in standard format
    """
    # option is "u" for user or "g" for group
    if option == "u":
        option_name = "userid"
    elif option == "g":
        option_name = "groupid"
    else:
        _stop_with_error(f"Unknown option: {option}")

    # Run beegfs-ctl command with CSV output
    command = f"beegfs-ctl --getquota --{option_name} {account} --csv"
    output = _shell_command(command).strip()

    # Parse CSV output: name,id,space_used,space_limit,inodes_used,inodes_limit
    # Example: mbjorgve,200697,204134154240,0,836440,0
    lines = output.split('\n')
    if len(lines) < 2:
        _stop_with_error(f"Unexpected quota output format: {output}")

    # Skip header line, use data line
    data = lines[1].split(',')
    if len(data) < 6:
        _stop_with_error(f"Unexpected quota CSV format: {lines[1]}")

    space_used_bytes = int(data[2])
    space_limit_bytes = int(data[3]) if data[3] != "0" else None
    inodes_used = int(data[4])
    inodes_limit = int(data[5]) if data[5] != "0" else None

    return {
        "space_used_bytes": space_used_bytes,
        "space_soft_limit_bytes": space_limit_bytes,
        "space_hard_limit_bytes": space_limit_bytes,
        "inodes_used": inodes_used,
        "inodes_soft_limit": inodes_limit,
        "inodes_hard_limit": inodes_limit,
    }


def _beegfs8_quota(option, account, _):
    """Query quota using modern beegfs command (BeeGFS 8.x).

    Args:
        option: "u" for user or "g" for group
        account: username or group name

    Returns:
        dict: quota information in standard format
    """
    # option is "u" for user or "g" for group
    if option == "u":
        flag = "--uids"
        type_filter = "user"
    elif option == "g":
        flag = "--gids"
        type_filter = "group"
    else:
        _stop_with_error(f"Unknown option: {option}")

    # For current user/groups, use "current" and filter by account name
    # since only root can query arbitrary user/group IDs
    current_user = pwd.getpwuid(os.getuid()).pw_name
    current_groups = _shell_command("id -Gn").split()

    if option == "u" and account == current_user:
        account_arg = "current"
        filter_name = account
    elif option == "g" and account in current_groups:
        account_arg = "current"
        filter_name = account
    else:
        # Try with the account name directly (may fail if not root)
        account_arg = account
        filter_name = account

    command = f"beegfs quota list-usage --output ndjson {flag} {account_arg}"
    output_raw = _shell_command(command)

    record = None
    for line in output_raw.splitlines():
        line = line.strip()
        if not line or line.startswith("INFO"):
            continue

        try:
            data = json.loads(line)
            if data["type"] == type_filter and data["name"] == account:
                record = data
                break
        except json.JSONDecodeError as e:
            _stop_with_error("Failed to parse `beegfs quota list-usage` output")

    if not record:
        return None
    
    # Parse space (used/limit)
    space_used_str, space_limit_str = record["space"].split("/")
    space_used_bytes = _parse_beegfs_size(space_used_str)
    space_limit_bytes = None if space_limit_str == '∞' else _parse_beegfs_size(space_limit_str)

    # Parse inodes (used/limit)
    inode_used_str, inode_limit_str = record["inode"].split("/")
    inodes_used = _parse_beegfs_count(inode_used_str)
    inodes_limit = None if inode_limit_str == '∞' else _parse_beegfs_count(inode_limit_str)

    return {
        "space_used_bytes": space_used_bytes,
        "space_soft_limit_bytes": space_limit_bytes,
        "space_hard_limit_bytes": space_limit_bytes,
        "inodes_used": inodes_used,
        "inodes_soft_limit": inodes_limit,
        "inodes_hard_limit": inodes_limit,
    }


def _lustre_quota_using_command(command):
    output = _shell_command(command)

    (
        _,
        space_used_kib,
        space_soft_limit_kib,
        space_hard_limit_kib,
        _,
        inodes_used,
        inodes_soft_limit,
        inodes_hard_limit,
        _,
    ) = output.split()

    # lustre adds a "*" if we are beyond quota
    # here we remove that "*", otherwise it messes up the rest of the code
    space_used_kib = space_used_kib.replace("*", "")
    inodes_used = inodes_used.replace("*", "")

    # all space quota numbers are initially in KiB and we convert to bytes
    space_used_bytes = 1024 * int(space_used_kib)
    if space_soft_limit_kib == "0":
        space_soft_limit_bytes = None
    else:
        space_soft_limit_bytes = 1024 * int(space_soft_limit_kib)
    if space_hard_limit_kib == "0":
        space_hard_limit_bytes = None
    else:
        space_hard_limit_bytes = 1024 * int(space_hard_limit_kib)

    inodes_used = int(inodes_used)
    if inodes_soft_limit == "0":
        inodes_soft_limit = None
    else:
        inodes_soft_limit = int(inodes_soft_limit)
    if inodes_hard_limit == "0":
        inodes_hard_limit = None
    else:
        inodes_hard_limit = int(inodes_hard_limit)

    return {
        "space_used_bytes": space_used_bytes,
        "space_soft_limit_bytes": space_soft_limit_bytes,
        "space_hard_limit_bytes": space_hard_limit_bytes,
        "inodes_used": inodes_used,
        "inodes_soft_limit": inodes_soft_limit,
        "inodes_hard_limit": inodes_hard_limit,
    }


def _lustre_quota_using_option(option, account, file_system_prefix):
    command = f"lfs quota -q -{option} {account} {file_system_prefix} | grep {file_system_prefix}"
    return _lustre_quota_using_command(command)


def _lustre_quota_using_path(path, file_system_prefix):
    project_id = int(_shell_command(f"lfs project -d {path} | awk '{{print $1}}'"))
    if project_id == 0:
        # workaround for projects that do not have quota set
        # in this case the path does not have quota and information would default
        # to project ID 0 which on our cluser gave space used by entire cluster
        return {
            path: {
                "space_used_bytes": "unknown",
                "space_soft_limit_bytes": None,
                "space_hard_limit_bytes": None,
                "inodes_used": "unknown",
                "inodes_soft_limit": None,
                "inodes_hard_limit": None,
            }
        }
    else:
        command = f"lfs quota -q -p {project_id} {file_system_prefix} | head -n 1"
        return {path: _lustre_quota_using_command(command)}


def _beegfs_quota_using_path(path, file_system_prefix):
    return {}


def _valid_project_paths(projects, project_path_prefixes):
    result = []
    for project in projects:
        for project_path_prefix in project_path_prefixes:
            path = os.path.join(project_path_prefix, project)
            if os.path.isdir(path):
                result.append((project, path))
    return result


def _quota_using_account(account, config, _quota_using_option, _quota_using_path):
    file_system_prefix = _get_option(config, "file_system_prefix")
    home_prefix = _get_option(config, "home_prefix")
    scratch_prefix = _get_option(config, "scratch_prefix")
    project_path_prefixes = _get_option(config, "project_path_prefixes").split(", ")
    path_based = _get_option(config, "path_based") == "yes"

    groups = _shell_command(f"id -Gn {account}").split()

    d = {}
    if path_based:
        d.update(
            _quota_using_path(os.path.join(home_prefix, account), file_system_prefix)
        )
        for _, path in _valid_project_paths(groups, project_path_prefixes):
            d.update(_quota_using_path(path, file_system_prefix))
    else:
        res_u = _quota_using_option("u", account, file_system_prefix)
        if res_u:
            d[file_system_prefix] = res_u
        
        res_home = _quota_using_option("g", account + "_g", file_system_prefix)
        if res_home:
            d[os.path.join(home_prefix, account)] = res_home

        res_scratch = _quota_using_option("g", account, file_system_prefix)
        if res_scratch:
            d[os.path.join(scratch_prefix, account)] = res_scratch
        
        for group, path in _valid_project_paths(groups, project_path_prefixes):
            d.update(_quota_using_path(path, file_system_prefix))
            d.update({path: _quota_using_option("g", group, file_system_prefix)})
    return d


def _quota_using_project(project, config, _quota_using_option, _quota_using_path):
    file_system_prefix = _get_option(config, "file_system_prefix")
    project_path_prefixes = _get_option(config, "project_path_prefixes").split(", ")
    path_based = _get_option(config, "path_based") == "yes"

    d = {}
    if path_based:
        for _, path in _valid_project_paths([project], project_path_prefixes):
            d.update(_quota_using_path(path, file_system_prefix))
    else:
        for group, path in _valid_project_paths([project], project_path_prefixes):
            d.update(_quota_using_path(path, file_system_prefix))
            d.update({path: _quota_using_option("g", group, file_system_prefix)})
    return d


def quota_using_path(config_file, cluster, path):
    config = _parse_config(config_file, cluster)
    file_system = _get_option(config, "file_system")
    file_system_prefix = _get_option(config, "file_system_prefix")

    if file_system == "lustre":
        return _lustre_quota_using_path(path, file_system_prefix)
    elif file_system in ("beegfs", "beegfs7", "beegfs8"):
        _stop_with_error("path-based query not implemented for beegfs")
    else:
        _stop_with_error(f"file system {file_system} is not implemented")


def quota_using_project(config_file, cluster, project):
    config = _parse_config(config_file, cluster)
    file_system = _get_option(config, "file_system")

    if file_system == "lustre":
        _quota_using_option = _lustre_quota_using_option
        _quota_using_path = _lustre_quota_using_path
    elif file_system in ("beegfs", "beegfs7"):
        _quota_using_option = _beegfs7_quota
        _quota_using_path = _beegfs_quota_using_path
    elif file_system == "beegfs8":
        _quota_using_option = _beegfs8_quota
        _quota_using_path = _beegfs_quota_using_path
    else:
        _stop_with_error(f"file system {file_system} is not implemented")

    return _quota_using_project(project, config, _quota_using_option, _quota_using_path)


def quota_using_account(config_file, cluster, account):
    config = _parse_config(config_file, cluster)
    file_system = _get_option(config, "file_system")

    if file_system == "lustre":
        _quota_using_option = _lustre_quota_using_option
        _quota_using_path = _lustre_quota_using_path
    elif file_system in ("beegfs", "beegfs7"):
        _quota_using_option = _beegfs7_quota
        _quota_using_path = _beegfs_quota_using_path
    elif file_system == "beegfs8":
        _quota_using_option = _beegfs8_quota
        _quota_using_path = _beegfs_quota_using_path
    else:
        _stop_with_error(f"file system {file_system} is not implemented")

    return _quota_using_account(account, config, _quota_using_option, _quota_using_path)


def _debug_quota_using_account(config_file, cluster, account):
    return {
        "/cluster/home/somebody": {
            "inodes_hard_limit": 110000,
            "inodes_soft_limit": 100000,
            "inodes_used": 90000,
            "space_hard_limit_bytes": 32212254720,
            "space_soft_limit_bytes": 21474836480,
            "space_used_bytes": 369164288,
        },
        "/cluster/projects/nn1234k": {
            "inodes_hard_limit": 1000000,
            "inodes_soft_limit": 1000000,
            "inodes_used": 1,
            "space_hard_limit_bytes": 1099511627776,
            "space_soft_limit_bytes": 1099511627776,
            "space_used_bytes": 800000000000,
        },
    }
