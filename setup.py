import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="photobooth",
    version="0.0.1",
    author="Ian Price",
    author_email="ianmprice@gmail.com",
    license='MIT',
    description="An rpi photobooth",  # pylint: disable=E501; # noqa: E501
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/namachieli/rpi_photobooth",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.7",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
        "Development Status :: 1 - Pre-Alpha"
    ],
    python_requires='>=3.7.3',
    include_package_data=True,
    install_requires=[
        "RPi.GPIO>=0.7.0",
        "Adafruit-Blinka>=6.5.0",
        "adafruit-circuitpython-neopixel>=6.0.3",
        "python-escpos==2.2.0",
        "aiofiles>=0.6.0",
        "aiohttp>=3.7.4"
    ]
)
