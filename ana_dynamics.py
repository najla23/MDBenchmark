#!/usr/bin/env python3
        
import os, shutil, glob, sys, math, argparse
from molecule_db import *
from simtable    import *

csb = "HOST" in os.environ and os.environ["HOST"].find("csb") >= 0
Debug = False

def use_sim(simtable:dict, mol:str, temp: int) -> bool:
    if not mol in simtable or not temp in simtable[mol]:
        print("Cannot find mol %s, temp %g in simtable. Sorry." % ( mol, temp ))
        return False
    if csb and simtable[mol][temp]["host"].find("csb") >= 0:
        return True
    if not csb and simtable[mol][temp]["host"].find("keb") >= 0:
        return True
    if Debug:
        boolname = { False: "False", True: "True" }
        print("csb: %s host: %s" % ( boolname[csb], simtable[mol][temp]["host"]))
    return False
    
def job_header(outf, ncores:int):
    outf.write("#!/bin/bash\n")
    outf.write("#SBATCH -t 24:00:00\n")
    if not csb:
        outf.write("#SBATCH -A SNIC2021-3-8\n")
    else:
        outf.write("#SBATCH -p CLUSTER-AMD\n")
    outf.write("#SBATCH -n %d\n" % ncores)
    
def run_rdf(job:str, rdfout:str, tbegin:float, tend:float, traj:str, tpr: str, force:bool):
    if os.path.exists(rdfout):
        if not (force or os.path.getmtime(traj) > os.path.getmtime(rdfout)):
            return
    with open(job, "w") as outf:
        job_header(outf, 1)
        outf.write("gmx rdf -sel 0 -ref 0 -dt 1 -f %s -s %s -o %s -b %d -e %d \n" % ( traj, tpr, rdfout, tbegin, tend ))
    os.system("sbatch %s" % job)

def run_rotacf(jobname: str, compound:str, tbegin: float, tend: float, traj: str, tpr: str,
               indexdir: str, rotacfout: str, rotplane: str, msdout: str, force:bool):
    # If files exist, do nothing, except when trajectory is newer.
    planendx = ( "%s/%s_rotplane.ndx" % ( indexdir, compound ))
    if os.path.exists(rotacfout) and os.path.exists(msdout) and (os.path.exists(rotplane) or not os.path.exists(planendx)):
        if not (force or os.path.getmtime(traj) > os.path.getmtime(rotacfout)):
            return
    with open(jobname, "w") as outf:
        job_header(outf, 1)
        outf.write("gmx rotacf -d -n %s/%s_rotaxis.ndx -f %s -s %s -o %s -b %d -e %d \n" % ( indexdir, compound, traj, tpr, rotacfout, tbegin, tend ))
        if os.path.exists(planendx):
            outf.write("gmx rotacf -n %s -f %s -s %s -o %s -b %d -e %d \n" % ( planendx, traj, tpr, rotplane, tbegin, tend ))
        outf.write("echo 0 | gmx msd -f %s -s %s -o %s -b %d -e %d \n" % ( traj, tpr, msdout, tbegin, tend ))
    os.system("sbatch %s" % jobname)

def run_epot(jobname:str, epotout:str, edr:str, nmol:int, force:bool):
    if os.path.exists(epotout):
        if not (force or os.path.getmtime(edr) > os.path.getmtime(epotout)):
            return
    with open(jobname, "w") as outf:
        job_header(outf, 1)
        outf.write("echo Potential | gmx energy -nmol %d -f %s -o %s\n" % ( nmol, edr, epotout ))
    os.system("sbatch %s" % jobname)
    
def ana_dynamics(simtable_files:list, mols:list, length:int, force:bool, rdf:bool):
    simtable = get_simtable(simtable_files)
    if Debug:
        print(simtable.keys())
    pwd = os.getcwd()
    if Debug:
        print("pwd %s" % pwd)
    os.chdir("bcc/melt")
    mol_list = simtable.keys()
    if None != mols:
        mol_list = mols
    for molname in mol_list:
        os.makedirs(molname, exist_ok=True)
        os.chdir(molname)
        for temp in simtable[molname]:
            if use_sim(simtable, molname, temp):
                if Debug:
                    print("%s %f" % ( molname, temp ))
                jobname = ("%s_%g.sh" % ( molname, temp ))
                simdir  = simtable[molname][temp]["simdir"] + "/"
                traj    = simdir + simtable[molname][temp]["trrfile"]
                tpr     = simdir + simtable[molname][temp]["tprfile"]
                rotacfout = ("rotacf_%g.xvg" % temp )
                rotplane  = ("rotplane_%g.xvg" % temp )
                msdout    = ("msd_%g.xvg" % temp )
                indexdir  = "../../../index"
                tend      = simtable[molname][temp]["length"]
                tbegin    = tend-length
                run_rotacf(jobname, molname, tbegin, tend, traj, tpr,
                           indexdir, rotacfout, rotplane, msdout, force)
                job       = ( "epot_%g.sh" % temp )
                epotout   = ( "epot_%g.xvg" % temp )
                run_epot(job, epotout, simdir+simtable[molname][temp]["edrfile"], simtable[molname][temp]["nmol"], force)
                if rdf:
                    rdfout    = ("rdf_%g.xvg" % temp)
                    job       = rdfout[:-3] + "sh"
                    run_rdf(job, rdfout, tbegin, tend, traj, tpr, force)
                if len(simtable[molname][temp]["grofile"]) > 4:
                    finalgro  = simdir + simtable[molname][temp]["grofile"] 
                    dstf      = ("final_%g.gro" % temp )
                    if Debug:
                        print("Will try to copy %s to %s if needed" % ( finalgro, dstf ) )
                    if os.path.exists(finalgro) and (not os.path.exists(dstf) or os.path.getmtime(finalgro) > os.path.getmtime(dstf)):
                        shutil.copyfile(finalgro, dstf)
        os.chdir("..")
    os.chdir(pwd)

def do_rotacf(mols:list, length: int):
    tend      = 15000
    tbegin    = max(0, tend-length)
    traj      = "NPT.xtc"
    tpr       = "NPT.tpr"
    rotacfout = "rotacf.xvg"
    rotplane  = "rotplane.xvg"
    msdout    = "msd.xvg"
    jobname   = "rotacf.sh"
    indexdir  = "../../../../index"
    for compound in mols:
        if Debug:
            print("Looking for %s" % compound)
        if os.path.isdir(compound):
            os.chdir(compound)
            for temp in glob.glob("*"):
                if os.path.isdir(temp):
                    os.chdir(temp)
                    final_gro = "NPT2.gro"                
                    if os.path.exists(final_gro):
                        run_rotacf(jobname, compound, tbegin, tend, traj, tpr,
                                   indexdir, rotacfout, rotplane, msdout, False)
                    os.chdir("..")
            os.chdir("..")

def parseArguments():
    parser = argparse.ArgumentParser(
      prog='ana_dynamics.py',
      description=
"""
Script to analyse dynamics in solid or melting simulations.
""")
    parser.add_argument("-mols", "--molecules", nargs="+", help="The molecule(s) to analyze, if none is given all will be analysed", type=str, default=None)
    length = 200
    parser.add_argument("-length", "--length", help="length of trajectory to analyse in ps, default "+str(length), type=int, default=length)
    parser.add_argument("-v", "--verbose", help="Print debugging info", action="store_true")
    parser.add_argument("-force", "--force", help="Run analysis even if data is present already", action="store_true")
    parser.add_argument("-solid", "--solid", help="Analyse solid simulations rather than melting simulations", action="store_true")
    parser.add_argument("-rdf", "--rdf", help="Run RDF analyses as well (slow!)", action="store_true")
    return parser.parse_args()
    
if __name__ == '__main__':

    if shutil.which("gmx") == None:
        sys.exit("Please load the gromacs environment using\nml load GCC/10.2.0  OpenMPI/4.0.5 GROMACS/2021")
    args = parseArguments()

    if args.solid:
        for top in [ "bcc", "resp" ]:
            if Debug:
                print("Looking for %s" % top)
            if os.path.isdir(top):
                os.chdir(top)
                phase = "solid"
                if os.path.isdir(phase):
                    os.chdir(phase)
                    if None != args.mols:
                        do_rotacf(args.mols, args.length)
                    os.chdir("..")
                os.chdir("..")
    else:
        simtabs = [ "csb_simtable.csv", "keb_simtable.csv" ]
        ana_dynamics(simtabs, args.molecules, args.length, args.force, args.rdf)

