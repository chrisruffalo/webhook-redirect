from setuptools import setup

setup(
   name='webhook-redirect',
   version='1.0',
   description='A package to allow redirecting webhooks',
   author='Chris Ruffalo',
   author_email='a@b.com',
   packages=['webhook-redirect'],
   install_requires=['Flask', 'requests', 'PyYAML']
)