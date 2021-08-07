import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="photobooth",
    version="0.0.1",
    author="Namachieli",
    license='MIT',
    description="A Photobooth Framework",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/capturingtime/photobooth",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.7",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: BSD-3-Clause",
        "Development Status :: 1 - Pre-Alpha"
    ],
    python_requires='>=3.7.3',
    include_package_data=True,
    install_requires=[
        "RPi.GPIO>=0.7.0",
        "Adafruit-Blinka>=6.5.0",
        "adafruit-circuitpython-neopixel>=6.0.3",
        "python-escpos==2.2.0",
        "django>=3.2.3"
    ]
)
