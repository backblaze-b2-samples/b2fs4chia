# b2fs4chia - FUSE for Backblaze B2 optimized for Chia
 
*WARNING*: this is an _experimental_ version. Use at your own risk.  

*WARNING*: it was never tested for anything other than Chia _quality check_ and _full proof_

*WARNING*: cache eviction is not implemented!


## Challenge

Passing the Chia _quality check_ within recommended 5s is easy, but that's just ~7 seeks.  
The real issue with harvesting Chia plots in the cloud is _full proof_, which is ~64 seeks, and this happens after the _quality check_ completes and must be completed and propagated in the Chia distributed network before the 30s timeout.

Those 7+64 seeks, in Chia 1.1.5, happen sequentially, which with variable latency can lead to enormous _full proof_ durations (>1min/proof is not unheard of)


## Factors impacting speed

### cache

Reads done by the _quality check_ can be reused to do a subsequent _full proof_, cutting reads from 7+64 down to 64

### prefetch

Chia reads are between 8 and 16KB and they usually happen in two subsequent `read()` calls.  
It's ~50ms faster to get the entire 16KB within one request to B2. It is suspected that this gain is so small, because server has some cache of its own (small subsequent reads _are_ faster than random reads). `50ms*64 = 3.2s`

### parallelization

Chia 1.1.5 uses `chiapos` which runs all read requests in sequence, but community [provided](https://www.google.com) [PRs](https://www.google.com) which parallelize the reads. This lets us reduce the full proof cost from total duration of 64 sequential reads over the network down to ~7 (and the first one can be cached, too)

### fast B2 cluster

B2 currently has 4 clusters. Performance of one cluster may be different from performance of another cluster.

### fast connection to B2

The harvester machine needs to be as close as possible (network-wise) to the B2 cluster which hosts our account

## Installation

NOTE: the following installation instruction is not very secure (it doesn't use checksums to verify integrity of PRs)

In order to make _full proof_ verification viable on B2, we need the harvester to have a few things:
1. FUSE driver to interface harvester with plots stored in a B2 bucket (it also has cache and takes care of the prefetch)
2. Modified chiapos to parallelize the full proof reads
3. Fast B2 cluster - currently accounts are assigned to cluster 000. You'd need to talk to B2 support to get an account 001 or 002
4. Fast connection to B2 - depends on where your cluster is. It's way easier to move harvester to cluster, than to move cluster to harvester!

### Installation of b2fs4chia FUSE driver

Clone this repository (`git clone ...`)
```
cd b2fs4chia
pip3 install .
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
pip install chia-blockchain==1.1.5
```

if this fails try

```
pip install pip --upgrade
```

#### Installation of modified chiapos

First, remove `chiapos` installed by `chia-blockchain`:

```
pip uninstall chiapos
```

You can make sure that worked by doing:
```
python -c 'import chiapos'
```

You should get a `ModuleNotFound` error.

Next, checkout `chiapos` repo and install a patched version of it.

```
git clone https://github.com/Chia-Network/chiapos.git
cd chiapos
git fetch origin pull/239/head:pr239
git checkout 1.0.1
git cherry-pick pr239
python setup.py develop  # this step requires cmake > 3.14.0 and python3 headers (sudo apt-get install python3-dev on debian-like distros)
```

## Configuration

You will need a `config.yaml` file in the folder where you run the fuse driver.
An example config ("config.yaml"):

```
accountId: <youraccountid>
applicationKey: <yourapplicationid>
bucketId: <yourbucketid>
```
to get `bucketId` you can use `b2 get-bucket <bucketname>` from B2 command line tool.

## Running

```
mkdir /tmp/fuse
b2fs4chia /tmp/fuse --cache_timeout 3600
```

### Testing

All commands related to chia have to be run from within the venv created a few steps above. To activate it in a new tab/session:

```
source ~/chia/bin/activate
```

```
chia init  # this is only required when running chia for the first time. Output may conatain other commands to perform
chia plots add -d /tmp/fuse
time chia plots check -n 5 -g "FULL-PLOT-FILE-NAME.plot"  # just the name, not the path
```
note the number of proofs and the time it took to fetch them

# License

MIT license (see LICENSE file)

`b2fs4chia` is based on `b2_fuse` by Sondre Engebraaten (MIT license)
