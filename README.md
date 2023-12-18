# dusage

Show disk usage and quota on a cluster.
Supports BeeGFS and Lustre but is probably still too hard-coded for "our" clusters
and path locations.

![screenshot](img/screenshot.png)

Available options:

```console
$ dusage --help

Usage: dusage [OPTIONS]

Options:
  -u, --user TEXT     The username to check (default: *****).
  -p, --project TEXT  The allocation project.

  --no-colors         Disable colors.
  --help              Show this message and exit.
```


## Separation into a front-end and a back-end

This effort is on-going. The back-end is taking shape (see below), but the
front-end still needs quite a bit of work. Essentially, the front-end is
missing and the back-end is not yet used.


## Front-end

Work in progress. More documentation soon.


## Back-end

Design choices:
- All back-end code is contained within one file:
  [dusage_backend.py](_dusage/dusage_backend.py)
- Local configuration can be done outside the Python code. Example:
  [dusage.cfg](_dusage/dusage.cfg)
- No external library dependencies. Only depends on the standard library.
- Interface functions return a dictionary instead of a
  [dataclass](https://docs.python.org/3/library/dataclasses.html) (which we
  wanted to use initially) to work on old Python versions typically found on
  clusters.
- All functions that start with an underscore are internal.

The back-end provides 3 interface functions:
- `quota_using_account`
- `quota_using_project`
- `quota_using_path`
