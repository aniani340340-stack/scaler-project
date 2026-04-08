# server/app.py
from openenv import OpenEnv

def main():
    env = OpenEnv()
    env.start()

if __name__ == "__main__":
    main()