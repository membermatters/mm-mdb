# mm-mdb
mm-mdb is a python script that connects to an MDB enabled vending machine and processes payments via member matters memberbucks.

# Getting Started
WiringPi must be installed on the Raspberry Pi. This can be done by going 
[here](https://github.com/WiringPi/WiringPi/releases) and downloading the latest armhf .deb file. Once you have it,
install it with:
```
sudo apt install ./wiringpi_3.2-bullseye_armhf.deb
```

Install required python packages by running the following command:
```
sudo apt install python3-dev
pip3 install -r requirements.txt
```

run mm-mdp.py with the following command:
```
python3 mm-mdb.py
```