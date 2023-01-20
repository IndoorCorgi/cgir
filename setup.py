from setuptools import setup

setup(
    name='cgir',
    version='1.2',
    description='Libraries and command line tool to control infrared LEDs and receivers on Raspberry Pi',
    author='Indoor Corgi',
    author_email='indoorcorgi@gmail.com',
    url='https://github.com/IndoorCorgi/cgir',
    license='Apache License 2.0',
    packages=['cgir'],
    install_requires=['docopt', 'pigpio'],
    entry_points={'console_scripts': ['cgir=cgir:cli',]},
    python_requires='>=3.6',
)
