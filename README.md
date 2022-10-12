# IncrementalBackup - a rsync backup manager

## Python script to create incremental backups using rsync

IncrementalBackup is a simple to use rsync wrapper for creating incremental
backups. It allows multiple source directories to be backuped at once and
provides multiple tests to ensure a safe backup procedure.

IncrementalBackup will check the existance of the source- and destination
directories, as well as check-files that ensure that a backup from / to the
specified directory is intended and possible. This is especially useful if the
backup is done to an external hard drive. If it is not connected, no backup will
be done and rsync will not be executed.

If the maximum number of backups at the destination location is reached
(if specified; see `--keep`), the oldest backup will be recycled to reduce the
runtime.

## How can I use IncrementalBackup?

Execute `python3 IncrementalBackup.py --help` to get the following help 
message / parameter list.

### Parameters

```
usage: IncrementalBackup.py --src <path>|<id>~#~<path> [<path>|<id>~#~<path> ...] --dst <path> [-h] [--version] [--keep <pos_num>] [--exclude <path>|<id>~#~<path> [<path>|<id>~#~<path> ...]]
                            [--dst_fqdn True|False]

IncrementalBackup.py is a wrapper for rsync and provides an easy interface for a safe and efficient backup process.

The script will perform the following checks before executing rsync:
- Do the source- and destination- directories exist?
- Do the source- and destination- check-files exist? (to ensure that the provided paths are correct)

IncrementalBackup.py will execute rsync with the --link-dest argument to create hard-links for files that did not change.
When using the --keep option, IncrementalBackup.py will also recycle old backups to reduce the runtime.

Have a look at the README.md file and the Github repository for more information.
https://github.com/Andreas-Menzel/IncrementalBackup
    

required arguments:
  --src <path>|<id>~#~<path> [<path>|<id>~#~<path> ...]
                        Data directories (+ identifiers).
  --dst <path>          Backup directory.

optional arguments:
  -h, --help            Show this help message and exit
  --version             Show the program's version number and exit
  --keep <pos_num>      Number of backups to keep. 0 = no limit (default). NOTE: THIS WILL DELETE ALL BUT THE LAST <pos_num> BACKUPS!
  --exclude <path>|<id>~#~<path> [<path>|<id>~#~<path> ...]
                        Paths (+ source identifiers) to exclude from the backup.
  --dst_fqdn True|False
                        Add fully qualified domain name to the backup path. Default is True.

Examples:

    Basic backup:
        python3 IncrementalBackup.py --scr /data --dst /backup
    
    ... with excludes:
        python3 IncrementalBackup.py --src /data --dst /backup --exclude /data/exclude_me/ /data/me_too.md

    Backup multiple sources:
        python3 IncrementalBackup.py --scr DATA~#~/data WWW~#~/var/www --dst /backup

    ... with excludes:
        python3 IncrementalBackup.py --src DATA~#~/data WWW~#~/var/www --dst /backup --exclude DATA~#~/data/exclude_me/ WWW~#~/var/www/me_too.md
```

### Explanation

#### Specify data- and backup-directory (required)

Use `--src` and `--dst` to specify the paths to the data *(source)* and
backup *(destination)* directories.

```
python3 IncrementalBackup.py --scr /data --dst /backup
```

You can also specify more than one source directory. In this case a unique id
must be assigned to each source in the format `<id>~#~<path>`:

```
python3 IncrementalBackup.py --scr DATA~#~/data WWW~#~/var/www --dst /backup
```

You can also assign an id to the source if you are only using one source
directoy. This is not required, however.

#### (Don't) save backup to FQDN subfolder (optional)

You may have noticed, that the backup will be saved to a subfolder of `--dst` 
named by the fully-qualified-domain-name of the computer. This feature is
enabled by default and was implemented so one can easily see where the backups
come from.

You can disable this feature by specifying `--dst_fqdn`:

```
python3 IncrementalBackup.py --src /data --dst /backup --dst_fqdn False
```

#### Exclude files and direcories from the backup (optional)

Use `--exclude` to exclude one or multiple files and / or directories from the
backup:

```
python3 IncrementalBackup.py --src /data --dst /backup --exclude /data/exclude_me/ /data/me_too.md
```

**If the source was assigned an id, the id must be forwarded to the
exclude-paths:**

Again: use the format `<id>~#~<PATH>`:

```
python3 IncrementalBackup.py --src DATA~#~/data WWW~#~/var/www --dst /backup --exclude DATA~#~/data/exclude_me/ WWW~#~/var/www/me_too.md
```

#### Limit number of backups (optional)

You can also limit the number of backups saved at the destination by specifying
`--keep`:

```
python3 IncrementalBackup.py --src /data --dst /backup --keep 5
```

**This will delete all but the latest 5 backups.** The fifth-latest backup will
be recycled; the execution time can be drastically reduced.


## Keep in mind

\<id\> and \<path\> must not contain the substring *~#~*.


## Error-Codes

**Code 1x - Error in function _process_argparse(...)**

- Code 11: \<keep\> must be positive int

- Code 12: \<dst_fqdn\> must be true, false, 0 or 1

**Code 2x: Error in function _process_arguments(...)**

- Code 21: One or more sources have an invalid key#value pair

- Code 22: Source-id is used more than once

- Code 23: One or more excludes have an invalid key#value
  pair

- Code 24: Exclude-ID was not assigned to any source

- Code 25: Exclude cannot be associated with any source

- Code 26: Exclude was not assigned an id

**Code 3x: Error in function _check_requirements(...)**

- Code 31: One or more data directories not found

- Code 32: Backup directory not found

- Code 33: One or more source-check-files not found

- Code 34: Destination-check-file not found


# Limitations

I know of the following limitations with this project. Please open an issue if
you find anything else. I will then fix the bug or at least add it to this
section.

- **Characters used in \<id\> and \<path\>**

  At the moment the \<id\> and the \<path\> must not contain the **"#"** character!