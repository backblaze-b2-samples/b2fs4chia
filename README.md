# b2fs4chia - FUSE for Backblaze B2 optimized for Chia
 
*IMPORTANT*: this is an _experimental_ version. Use at your own risk.  

*IMPORTANT*: This has only been tested for Chia _quality check_ and _full proof_ and nothing else

## Challenge

Passing the Chia _quality check_ within recommended 5s is easy, because this check involves doing ~7 seeks.  
The real issue with farming Chia plots in the cloud is doing the _full proof_, which is ~64 seeks, and this happens after the _quality check_ completes and must be completed and propagated in the Chia distributed network before the 30s timeout.

Those 7+64 seeks, in Chia 1.1.6, happen sequentially, which with variable latency can lead to enormous _full proof_ durations (>1min/proof is not unheard of)


## Factors impacting speed

### cache

Reads done by the _quality check_ can be reused to do a subsequent _full proof_, cutting reads from 7+64 down to 64

### prefetch

Chia reads are between 8 and 16KB and they usually happen in two subsequent `read()` calls.  
It's ~50ms faster to get the entire 16KB within one request to Backblaze B2. It is suspected that this gain is so small, because server has some cache of its own (small subsequent reads _are_ faster than random reads). `50ms*64 = 3.2s`

### parallelization

Chia 1.1.6 uses `chiapos` 1.0.2 which runs all read requests in sequence, but community [provided](https://www.google.com) [PRs](https://www.google.com) which can parallelize those reads. This lets us reduce the full proof cost from total duration of 64 sequential reads over the network down to ~7 (and the first one can be cached, too)

### Storage Perfomance

Storage performance may impact your results. Feel free to contact Backblaze B2 support if you notice performance issues.

### fast connection to B2

Having the harvester machine as close as possible (network-wise) to the Backblaze B2 region which hosts our account may help with performance.

## Installation

NOTE: the following installation instruction is not very secure (it doesn't use checksums to verify integrity of PRs)

In order to make _full proof_ verification viable on Backblaze B2, we need the harvester to have a few things:
1. FUSE driver to interface harvester with plots stored in a Backblaze B2 bucket (it also has cache and takes care of the prefetch)
2. Modified chiapos to parallelize the full proof reads
3. Fast connection to Backblaze B2 - depends on which region your account is in. It's way easier to move harvester to region, than to move region to harvester!

### Installation of b2fs4chia FUSE driver

Clone this repository (`git clone git@github.com:Backblaze-B2-Samples/b2fs4chia.git`), then install it
```
cd b2fs4chia
pip3 install --require-hashes -r requirements.txt
pip3 install --no-deps .
```
Optionally you can use a `venv` to install *b2fs4chia* separately from other python packages.


### Installation of chia-blockchain and modified chiapos

#### Start with a virtualenv

```
sudo apt-get install python3-venv
python3 -m venv ~/chia
source ~/chia/bin/activate
```

install a released version of chia-blockchain

```
pip install chia-blockchain==1.2.0
```

if this fails try `pip install pip --upgrade` first.


## Configuration

`b2fs4chia` connects to Backblaze B2 through the S3-compatible API. Configure it
with the standard Backblaze sample environment variables, or put the same keys in
a `config.yaml` file in the folder where you run the FUSE driver.

An example environment file is provided in `.env.example`:

```
B2_APPLICATION_KEY_ID=
B2_APPLICATION_KEY=
B2_BUCKET_NAME=
B2_REGION=
B2_PUBLIC_URL_BASE=
```

An example `config.yaml`:

```
B2_APPLICATION_KEY_ID: <your-application-key-id>
B2_APPLICATION_KEY: <your-application-key>
B2_BUCKET_NAME: <your-bucket-name>
B2_REGION: <your-b2-region>
B2_PUBLIC_URL_BASE: <your-public-url-base>
```

Use the bucket name, not the bucket ID. The S3 endpoint is derived from
`B2_REGION`. `B2_PUBLIC_URL_BASE` is optional; when provided, listed object
metadata includes a `publicUrl` value. Reads still use signed S3 requests.

### Migrating from the legacy config

Previous versions used `accountId`, `applicationKey`, and `bucketId` in
`config.yaml`, plus `--account_id` and `--bucket_id` CLI flags. This
S3-compatible version accepts those names as deprecated aliases, but S3 access
requires a bucket name and region.

For a rolling deploy, first expand the manifest so old and new keys are present:

```
accountId: <legacy-application-key-id>
applicationKey: <legacy-application-key>
bucketId: <legacy-bucket-id>
B2_APPLICATION_KEY_ID: <your-application-key-id>
B2_APPLICATION_KEY: <your-application-key>
B2_BUCKET_NAME: <your-bucket-name>
B2_REGION: <your-b2-region>
B2_PUBLIC_URL_BASE: <your-public-url-base>
```

Old processes continue to read the legacy keys. New processes read the
standard `B2_*` keys. After all nodes run the S3-compatible version, contract
the manifest by removing `accountId`, `applicationKey`, and `bucketId`.

## Running

```
mkdir /mnt/b2fs4chia
b2fs4chia /mnt/b2fs4chia --cache_timeout 3600
```

### Testing

All commands related to chia have to be run from within the venv created a few steps above. To activate it in a new tab/session:

```
source ~/chia/bin/activate
```

```
chia init  # this is only required when running chia for the first time. Output may conatain other commands to perform
chia plots add -d /mnt/b2fs4chia
time chia plots check -n 5 -g "FULL-PLOT-FILE-NAME.plot"  # just the name, not the path
```
note the number of proofs and the time it took to fetch them

# License

MIT license (see LICENSE file)

`b2fs4chia` is based on `b2_fuse` by Sondre Engebraaten (MIT license)
