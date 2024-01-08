import sys
import os
import subprocess
import configparser


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


def _beegfs_quota_using_option(option, account, _):
    command = f"beegfs-ctl --getquota --{option}id {account} --csv | grep {account}"

    # 0-th element since we only consider the first pool
    output = _shell_command(command).split("\n")[0]

    _, _, space_used_bytes, space_limit_bytes, inodes_used, inodes_limit = output.split(
        ","
    )

    if space_limit_bytes == "unlimited":
        space_limit_bytes = None
    else:
        space_limit_bytes = int(space_limit_bytes)
    if inodes_limit == "unlimited":
        inodes_limit = None
    else:
        inodes_limit = int(inodes_limit)

    return {
        "space_used_bytes": int(space_used_bytes),
        "space_soft_limit_bytes": space_limit_bytes,
        "space_hard_limit_bytes": space_limit_bytes,
        "inodes_used": int(inodes_used),
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
        command = f"lfs quota -q -p {project_id} {file_system_prefix}"
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
        d.update(
            {file_system_prefix: _quota_using_option("u", account, file_system_prefix)}
        )
        d.update(
            {
                os.path.join(home_prefix, account): _quota_using_option(
                    "g", account + "_g", file_system_prefix
                )
            }
        )
        d.update(
            {
                os.path.join(scratch_prefix, account): _quota_using_option(
                    "g", account, file_system_prefix
                )
            }
        )
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
    elif file_system == "beegfs":
        _stop_with_error("path-based query not implemented for beegfs")
    else:
        _stop_with_error(f"file system {file_system} is not implemented")


def quota_using_project(config_file, cluster, project):
    config = _parse_config(config_file, cluster)
    file_system = _get_option(config, "file_system")

    if file_system == "lustre":
        _quota_using_option = _lustre_quota_using_option
        _quota_using_path = _lustre_quota_using_path
    elif file_system == "beegfs":
        _quota_using_option = _beegfs_quota_using_option
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
    elif file_system == "beegfs":
        _quota_using_option = _beegfs_quota_using_option
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
