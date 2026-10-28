#!/usr/bin/env python3
"""Collect active experiment metadata and recent logs into the work reports folder."""
import argparse
from pathlib import Path
from legion_reports import collect

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:print('Report ZIP: '+str(collect(args.client,args.output)))
    except (ValueError,OSError,KeyError,TypeError) as error:
        parser.exit(1,'Report collection stopped: '+str(error)+'\n')
