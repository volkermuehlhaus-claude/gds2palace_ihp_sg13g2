# Python model code
The *.py files are Python model code to create a simulation model from *.gds layout and *.xml technology stackup. Each *.py file creates one simulation model, or to be more precise: the files required to run the AWS Palace simulation. These output files will be created in a directory "palace_model" next to the model's *.py file.

To run these Python files, you need to have the gdstk, gmsh, numpy and shapely modules installed (`pip install gds2palace` installs all of them). It is recommended to create a venv for this, and also install the scikit-rf module that we need for postprocessing the Palace simulation results.

# gds2palace, the 'machine room' of this workflow
The gds2palace folder contains the code modules required by this workflow. So far, this directory was always required in your current directory where you start the actual model code. 

New since November 2025: you can also install the gds2palace module into your venv using 
```
    pip install gds2palace
```
https://pypi.org/project/gds2palace/


# XML technology files
The *.xml technology files used by these models are located in [../XML_stackup/legacy](../XML_stackup/legacy), and [../XML_stackup/latest](../XML_stackup/latest) for palace_line_portwall.py. The models reference them by relative path from there. They include the technology description with materials, layer mappings and physical location in the stackup. They look similar to the files used by IHP openEMS workflow, but might be slightly different in the details to enable special "tricks" for Palace.

# GDSII layout files (including port shapes)
The *.gds files are the layouts for these examples. They include port shapes on special layers (typically 201 and above) that are referenced by the simulation model code. Ports in this Palace workflow are 2D sheets, so vertical via ports are drawn as zero width boxes (lines) in the xy plane. This makes it difficult to see them in the GDSII layout viewer. A via port shape with an area becomes a tube port instead: the four side walls of its bounding box (gds2palace 0.12.0 and newer).