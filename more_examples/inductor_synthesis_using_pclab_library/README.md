# Inductor synthesis using gds2palace and pcLab

The gds2palace example provided here creates a symmetric inductor layout in IHP SG13G2 technology fully automatically, based on a target L value at a target frequency. The geometry sweep range where possible implementations are evaluated is defined in the model code: range for width, spacing, number of turns. 

The layout implementation is done by [pcLab](https://github.com/dgrujic/pcLab). pcLab is a collection of Python classes that generate GDSII layouts of integrated passive structures such as inductors and baluns, created by Dušan Grujić. In this example, we use a local copy pf pclab with additional extensions that are not yet included in the upstream repository.

**NOTE: For inductor synthesis in IHP SG13G2 without need for an external geometry library, ![see this example](../inductor_synthesis_no_external_library/)**

![inductor_design](../../doc/png/rfic_inductor_finder.png)

## Principle of operation

This is what this script does for you:

- Step 1: Determine list of possible implementations based on close form equations, by calculating the required diameter and testing if this layout is valid and within a given maximum diameter limit. 
- Step 2: Create GDSII layouts for all these candidates using pcLab library
- Step 3: Create simulation ready GDSII layouts for gds2palace (including ports + ground return) using pin2port function
- Step 4: Run a fast FEM sweep over all candidates using gds2palace
- Step 5: Evaluate the n candidates with highest Q factor at target frequency and re-tune to target value at target frequency
- Step 6: After m iterations over step 5, select the candidate with the highest Q factor and do a wideband full sweep using gds2palace FEM with full accuracy.
- Step 7: Plot results for L and Q factor of that best candidate
- Step 8: Create a final GDSII file with all extra layout features required for SG13G2 OPDK.

The gds2palace FEM simulation flow runs in non-GUI mode here, so that there is no user action required while the script is processing data. 


## Usage

Acticate the Python venv where you can run gds2palace models. gds2palace must be installed as a Python module: pip install gds2palace. This example also needs gdspy, which gds2palace no longer installs (since 0.11.0): pip install gdspy. The Palace solver must be available and you must be able to run gds2palace models. If you are not familar with gds2palace, go to the gds2palace documentation [here](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2).

In the `synthesize_inductor_v11.py` script, set your target L value and target frequency, and adjust the search range for w,s and number of turns (valid range: 1 to 3 turns). Then just run the Python script.


## Change history

16-Mar-2026: Extended functionality for SG13 technology in this local copy of pclab. `synthesize_inductor_v11.py` now runs an extra step after simulating the final layout: it creates a "final" GDSII with special layout "decoration" for IHP SG13G2 OPDK, e.g. nofill polygons and PWell.block. It also adds pin shapes on metal layers and some description on layer TEXT.drawing 

![inductor_design](../../doc/png/rfic_inductor_finder3.png)

