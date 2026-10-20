import os
import time
import subprocess as sub
import sys

def environment(VENV,REQUIREMENTS):

    venv_path=os.path.join(os.getcwd(),VENV)
    python=os.path.join(venv_path, "Scripts" if os.name=='nt' else 'bin', "python.exe" if os.name=='nt' else 'python')
    requirements_path=os.path.join(os.getcwd(),REQUIREMENTS)

    if os.path.exists(python):

        print("Using virtual environment: "+VENV)

        if not(os.path.exists(requirements_path)):

            print(f"{requirements_path} NOT FOUND")
            return

        modules=open(requirements_path)

        for line in  modules:

            module=line.strip()

            result=sub.run([python, "-c" , f"import {module}"], capture_output=True)

            if result.returncode!=0:

                print(f"{module} not found")
                print(f"\n\nInstalling {module}...")

                sub.run([python, "-m", "pip", "install", module], check=True)

            else:
                print(f"{module} found")

    else:
        print("Virtual environment not found")
        print("Create virtual environment?")

        ch=input("Y/N?: ")

        if ch.upper()=="Y":
            sub.run([sys.executable, "-m", "venv", VENV])

            print("Using virtual environment: "+VENV)
            
            if not(os.path.exists(requirements_path)):
            
                print(f"{requirements_path} NOT FOUND")
                return
            
            modules=open(requirements_path)
            
            for line in  modules:
            
                module=line.strip()
            
                result=sub.run([python, "-c" , f"import {module}"], capture_output=True)
            
                if result.returncode!=0:
            
                    print(f"{module} not found")
                    print(f"\n\nInstalling {module}...")
            
                    sub.run([python, "-m", "pip", "install", module], check=True)
            
                else:
                    print(f"{module} found")

        else:
            print("Install dependencies globally?")
            ch=input("Y/N?: ")

            if ch.upper()=="Y":
                sub.run(f"pip install -r {requirements_path}")

            else:
                print("Exiting",end="",flush=True)
                for _ in range(3):
                    time.sleep(0.5)
                    print(".",end="", flush=True)
                    time.sleep(0.5)
                exit()