from setuptools import setup

setup(
    name='contentimportulearn',
    version='0.1',
    description='Custom import based on collective.exportimport',
    url='https://github.com/UPCnet/contentimportulearn.git',
    author='Plone Team',
    author_email='ploneteam@upcnet.es',
    license='GPL version 2',
    packages=['contentimportulearn'],
    include_package_data=True,
    zip_safe=False,
    entry_points={'z3c.autoinclude.plugin': ['target = plone']},
    install_requires=[
        "setuptools",
        "collective.exportimport",
        "beautifulsoup4",
        ],
    )
