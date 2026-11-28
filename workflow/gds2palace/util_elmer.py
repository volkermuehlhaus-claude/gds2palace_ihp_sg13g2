########################################################################
#
# Copyright 2025 Volker Muehlhaus and IHP PDK Authors
#
# Licensed under the GNU General Public License, Version 3.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.gnu.org/licenses/gpl-3.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
########################################################################

# This is additional code for the gds2palace from to implement the Elmer FEM output option
import os
import shutil
import subprocess
import platform

def write_elmer_frequencies (elmer_freq_file, 
                             fstart, 
                             fstop, 
                             fstep, 
                             f_discrete_list, 
                             f_dump_list):
        
        # write simulation frequencies for Elmer
        with open(elmer_freq_file, "w") as freqfile:  
            frequency_list = []
            
            if (fstart is not None) and (fstop is not None):
                f = fstart
                if (fstop > fstart) and (fstep > 0):
                    while f <= fstop:
                        frequency_list.append(f)
                        f = f + fstep                
                # always include last value
                if fstop not in frequency_list:
                    frequency_list.append(fstop)
            
            # append f_discrete_list 
            if len(f_discrete_list) > 0:
                frequency_list.extend(f_discrete_list)

            # append f_dump_list 
            if len(f_dump_list) > 0:
                frequency_list.extend(f_dump_list)

            # sort and write to file
            frequency_list.sort()

            # De-duplicate: Elmer's "Scanning" simulation solves one full pass per
            # line of frequencies.dat, addressed by index - a duplicate value on two
            # lines (whether bit-identical, or merely rounding to the same text
            # below) means Elmer silently re-solves the same physical frequency
            # twice. Coincidental overlap between the sweep, fpoint, and fdump (or
            # float drift from repeated "f = f + fstep" additions landing next to a
            # user-specified value) is common, so dedupe on the same 3-significant-
            # digit text written below rather than exact float equality.
            deduped = []
            seen = set()
            for freq in frequency_list:
                key = f"{freq:.3e}"
                if key not in seen:
                    seen.add(key)
                    deduped.append(freq)
            frequency_list = deduped

            for n, freq in enumerate(frequency_list):
                freqfile.write(f"{n+1}  {freq:.3e}\n")

            # store number of frequencies because we need to write that to physics.sif
            num_frequencies = n+1

        freqfile.close() 
        return num_frequencies  

def write_elmer_physics_file (unit,
                              elmer_physics_file,
                              num_frequencies,
                              Elmer_materials,
                              Elmer_bodies,
                              Elmer_boundaries,
                              Elmer_boundaries_PEC,
                              Elmer_ports,
                              PEC_boundaries,
                              PML_boundaries,
                              PMC_boundaries,
                              f_dump_list=None):

        with open(elmer_physics_file, "w") as f:

            # specify storage of dump files: only when fdump frequencies were requested,
            # since Elmer's "Scanning" simulation has no per-sample SaveStep like Palace -
            # this dumps fields at every solved frequency, not just the fdump-selected ones
            dump_requested = bool(f_dump_list)
            if dump_requested:
                item = '! Save vtu field dump files at every solved frequency (other options: "after timestep", "after all")\n'
            else:
                item = '! Dont save vtu files (other options: "after timestep", "after all")\n'
            item = item + f'Solver 3 :: Exec Solver = String "{"Always" if dump_requested else "never"}"\n\n'
            f.write(item + '\n')

            # frequency block that references output file frequencies.dat
            item = f'Simulation\n  timestep intervals(1) = {num_frequencies}\nend\n'
            f.write(item + '\n')

            item = 'Solver 1\n' 
            item = item + '   frequency = variable time\n'
            item = item + '     real\n'
            item = item + '       include frequencies.dat\n'
            item = item + '     end\n'
            item = item + 'End\n'
            f.write(item + '\n')


            # write Material sections
            for n,material in enumerate(Elmer_materials):
                materialname = material["name"]
                permittivity = material["permittivity"]
                conductivity = material["conductivity"]
                permeability = 1.0

                item = f'Material {n+1}\n   name = string "{materialname}"\n'
                item = item + f"   relative permittivity = {permittivity}\n"
                item = item + f"   electric conductivity = {conductivity}\n"
                item = item + f"   relative permeability = {permeability}\n"
                item = item + "End\n"
                f.write(item + "\n")

            # write Bodies sections
            for n,body in enumerate(Elmer_bodies):
                name = body["name"]
                material = body["material"]
                item = f'Body {n+1}\n   Equation = Integer 1\n'
                item = item + f'   Name = "{name}"\n'
                item = item + f"   material = {material}\n"
                item = item + "End\n"
                f.write(item + '\n')

            # write metal boundaries section
            for n,boundary in enumerate(Elmer_boundaries):
                name = boundary["name"]
                conductivity = boundary["conductivity"]
                thickness_SI = boundary["thickness"]*unit
                item = f'Boundary Condition {n+1}\n'
                item = item + f'   Name = "{name}"\n'
                item = item + f'   Layer Relative Reluctivity = Real 1.0\n'
                item = item + f'   Layer Electric Conductivity = Real {conductivity:.3f}\n'
                item = item + f"   Good Conductor BC = True\n"
                item = item +  '   ! Either use "good conductor" or give layer thickness.\n'
                item = item + f"   !Layer Thickness = {thickness_SI:.3e}\n"
                item = item + "End\n"
                f.write(item + '\n')

            # write port boundaries section
            for boundary in Elmer_ports:
                n = n+1 # continue number range started in metal boundaries
                name = boundary["name"]
                portnum = boundary["portnum"]
                portZ0 = boundary["Z0"]
                direction = boundary["direction"]
                item = f'Boundary Condition {n+1}\n'
                item = item + f'   Name = "{name}"\n'
                item = item + f'   Constraint Mode = {portnum}\n'
                item = item + f'   Port Type = String "rectangular"\n'
                item = item + f'   Port Impedance = Real {portZ0}\n'
                item = item + f'   Port Direction = Integer {direction}\n'
                item = item + "End\n"
                f.write(item + '\n')

            # write per-layer PEC boundaries section: a conductor/via/sheet layer that used the
            # reserved "PEC" material gets its own ideal-conductor boundary condition here, using
            # the exact same literal zero-tangential-E construct as the outer airbox PEC boundary
            # below - just scoped to this layer's own physical group instead of the shared one
            for name in Elmer_boundaries_PEC:
                n = n+1 # continue number range started in metal boundaries
                item = f'Boundary Condition {n+1}\n'
                item = item + f'   Name = "{name}"\n'
                item = item +  '   E re {e} = Real 0\n'
                item = item +  '   E im {e} = Real 0\n'
                item = item + "End\n"
                f.write(item + '\n')


            # write outer simulation boundary
            if len(PEC_boundaries) > 0:
                n = n+1
                name = 'PEC_boundary'
                item = f'Boundary Condition {n+1}\n'
                item = item + f'   Name = "{name}"\n'
                item = item +  '   E re {e} = Real 0\n'
                item = item +  '   E im {e} = Real 0\n'
                item = item + "End\n"
                f.write(item + '\n')


            if len(PML_boundaries) > 0:
                n = n+1
                name = 'Absorbing_boundary'
                item = f'Boundary Condition {n+1}\n'
                item = item + f'   Name = "{name}"\n'
                item = item + f'   Absorbing BC = True\n'
                item = item + "End\n"
                f.write(item + '\n')

            if len(PMC_boundaries) > 0:
                # No physics keywords needed: per the ElmerModelsManual VectorHelmholtz chapter,
                # the natural (Neumann) boundary condition of this curl-curl formulation - i.e.
                # what a boundary gets when no Robin/Dirichlet keyword is written for it at all -
                # is exactly the PMC (zero tangential H) condition. The mesh already carries a
                # physical group named 'PMC_boundary' for these faces (see util_simulation_setup.py),
                # so an explicit-but-empty block here is enough; Elmer applies the natural BC to it.
                n = n+1
                name = 'PMC_boundary'
                item = f'Boundary Condition {n+1}\n'
                item = item + f'   Name = "{name}"\n'
                item = item + "End\n"
                f.write(item + '\n')

        f.close()   


def write_case_and_solver_files (targetdir, order, iterative, ELMER_MPI_THREADS=1):
    # Elmer EM simulation: write case.sif and the solver files included there

    # set most efficient solver method 
    if order==2:
        solver_option = 'quadratic approximation = true'
        if iterative:
            solver_option = solver_option + '\n    include "quadratic-iterative.sif"'
        else:
            solver_option = solver_option + '\n    include "quadratic-direct.sif"'
    else:
        # order = 1
        solver_option = 'include "first-order.sif"'


    # extra settings for MPI parallel computing
    if ELMER_MPI_THREADS <= 6:
        increase = 0
    elif ELMER_MPI_THREADS <= 8:
        increase = 50
    elif ELMER_MPI_THREADS <= 12:
        increase = 100
    elif ELMER_MPI_THREADS <= 15:
        increase = 150
    else: 
        increase = 250


    casedata=f'''
    Check Keywords "warn"

    Header
    Mesh DB "mesh" "."
    End

    Simulation
    Coordinate Mapping(3) = Integer 1 2 3
    Coordinate Scaling = Real 1e-6
    Coordinate System = String "Cartesian"
    Simulation Type = String "Scanning"
    timestep sizes(1) = 1
    Steady State Max Iterations = Integer 1
    Steady State Min Iterations = Integer 0
    Use Mesh Names = Logical True
    output level = 10
    mesh levels = 1
    End

    Solver 1
    Procedure = File "VectorHelmholtz" "VectorHelmholtzSolver"
    Equation = String "curlcurl"
    Exec Solver = String "Always"
    
    use piola transform = true

    ! Here add option: 
    ! - quadratic approximation true
    !   - direct solver
    !   - iterative solver
    ! - quadratic approximation false
    
    {solver_option}
    
    Mumps percentage increase working space = integer {increase} ! table lookup for {ELMER_MPI_THREADS} MPI parallel runs

    constraint modes analysis = true
    Constraint Modes Matrix Results = true
    End


    Solver 2
    Equation = "calcfields"

    Procedure = "VectorHelmholtz" "VectorHelmholtzCalcFields"

    Calculate Elemental Fields = True
    Calculate Magnetic Field Strength = Logical True
    Calculate Magnetic Flux Density = Logical True
    !Calculate Poynting vector = Logical True
    !Calculate Div of Poynting Vector = Logical True
    Calculate Electric field = Logical True
    Calculate Energy Functional = Logical True

    Steady State Convergence Tolerance = 1
    Linear System Solver = "Iterative"
    Linear System Preconditioning = None
    Linear System Residual Output = 1000
    Linear System Max Iterations = 5000
    Linear System Iterative Method = CG
    Linear System Convergence Tolerance = 1.0e-9
    show angular frequency = logical true
    End

    Solver 3
    Ascii Output = Logical True
    Coordinate Scaling Revert = Logical True
    Equation = String "ResultOutput"
    Output File Name = File "fields"
    Procedure = File "ResultOutputSolve" "ResultOutputSolver"
    Vtu Format = Logical True
    Vtu Time Collection = Logical True
    save geometry ids = true
    End

    Solver 4
    Equation = "save scalars"
    procedure = "SaveData" "SaveScalars"
    Filename = scalar_results
    echo values = logical true
    parallel reduce = true
    End

    Equation 1
    Active Solvers(3) = Integer 1 2 3
    End

    Constants
    Permittivity Of Vacuum = Real 8.85419e-12
    End

    !!!!!!!!!!!

    include physics.sif
    '''


    case_filename = os.path.join(targetdir, 'case.sif')
    with open(case_filename, "w") as casefile:  
        casefile.write(casedata)
        casefile.close()    


    # -------------- first order solver recipe -------------------

    first_order = f'''
    Linear System Solver = direct
    Linear System Direct Method = zmumps
    '''

    filename = os.path.join(targetdir, 'first-order.sif')
    with open(filename, "w") as f:  
        f.write(first_order)
        f.close()    

    # -------------- quadratic solver recipe, direct -------------------

    quadratic_direct = f'''
    Quadratic Approximation = true
    second kind basis = false
    Linear System Solver = direct
    Linear System Direct Method = zmumps
    '''

    filename = os.path.join(targetdir, 'quadratic-direct.sif')
    with open(filename, "w") as f:  
        f.write(quadratic_direct)
        f.close()    

    # -------------- quadratic solver recipe, iterative -------------------
    quadratic_iterative = f'''
    Quadratic Approximation = true
    second kind basis = true

    Linear System Complex = logical True
    Linear System Symmetric = logical True
    Linear System Solver = Iterative
    Linear System Scaling = True
    Linear System Iterative Method = GCR
    Linear System Max Iterations = 50
    Linear System GCR Restart = 50
    Linear System Residual Output = 1
    Linear System Abort Not Converged = False
    Linear System Convergence Tolerance = 1.0e-6
    Linear System Preconditioning = Multigrid

    Edge Basis = True
    MG Method = p
    MG Levels = 2
    MG Smoother Relaxation Factor = $ 1/6
    MG Smoother = cjacobi
    MG Pre Smoothing iterations = 6
    MG Post Smoothing Iterations = 6
    MG Max Iterations = 1
    MG Preconditioning = none

    MG Lowest Linear Solver = Direct
    mglowest: Linear System Direct Method = zmumps
    '''
    
    filename = os.path.join(targetdir, 'quadratic-iterative.sif')
    with open(filename, "w") as f:  
        f.write(quadratic_iterative)
        f.close()  


#------------------------- Elmer thermal model -------------------------

def write_elmer_thermal_file (unit,
                                elmer_thermal_file,
                                Elmer_materials,
                                Elmer_bodies,
                                Elmer_boundaries,
                                Elmer_body_forces,
                                Elmer_thermal_boundaryconditions,
                                iterative=True,
                                heat_flux_output=False):
    """Write the case.sif of an Elmer thermal model.

    Always written: temperature (thermal_results*.vtu), its min/max (thermal_results.dat) and the heat flow through
    each constant-temperature boundary (thermal_heatflow.dat, in W, negative = out of the model).
    heat_flux_output: also write the heat flux (W/m^2) and the temperature gradient (K/m), per body."""

    with open(elmer_thermal_file, "w") as f:

        vtu_file = '../thermal_results.vtu'

        if iterative:
            # ILU3, not ILU1: the conductivity contrast (metal against passivation, about 500x) and the
            # ill-shaped tets gmsh leaves between thin layers make the matrix hard to precondition.
            # In tests on four thermal models, BiCGStabl with ILU1 failed on three of them (also CG, GCR
            # and IDRS with ILU1, and ILU2 on one), ILU3 converged on all four, mostly faster than ILU1
            # and the direct solver, with the same temperatures. A run that still doesn't converge stops
            # after 10000 iterations, within minutes, instead of running for an hour.
            # Tolerance 1e-10: the residual is relative to a right-hand side that holds the fixed temperatures
            # (about 300 K), so with 1e-7 a few mW could stay unbalanced: the heat flow through the boundaries
            # of a 70 mW interposer model summed to 0.4 % less than the input (3.3 % on a mesh with 3.5 times the
            # nodes), and its peak was 0.08 K low. With 1e-10 it balances, at the same run time.
            linear_system_block = '''Linear System Solver = Iterative
Linear System Iterative Method = BiCGStabl
Linear System Max Iterations = 10000
Linear System Convergence Tolerance = 1.0e-10
Linear System Preconditioning = ILU3'''
        else:
            # MUMPS is not available in the Windows Elmer build - UMFPACK ships
            # with Elmer on all platforms and needs no extra solver-specific options
            linear_system_block = '''Linear System Solver = Direct
Linear System Direct Method = umfpack'''

        # A temperature-dependent conductivity (a Variable Temperature table) is evaluated at the current temperature.
        # With a single heat solver iteration and no initial condition, that is 0 K, far below the table, where Elmer
        # extrapolates linearly (IHP's Si table: about 270 instead of 82 W/mK at 300 K). So iterate until converged,
        # starting from the lowest constant temperature of the model. Models without a table are unchanged.
        has_table = any("Variable Temperature" in str(m["thermalcond"]) for m in Elmer_materials)
        start_temp = min((bc["temp"] for bc in Elmer_thermal_boundaryconditions), default=None) if has_table else None
        if has_table:
            linear_system_block += '''
Nonlinear System Max Iterations = 50
Nonlinear System Convergence Tolerance = 1.0e-6'''

        # Heat flow through each constant-temperature boundary: the sum of the nodal heat loads (the residual of the
        # heat equation, "temperature loads") on its nodes, one SaveScalars mask per boundary. These sums balance the
        # input power on any mesh, so they show where the heat goes, not how accurate the mesh is.
        # Parallel Reduce: with MPI, one file summed over the partitions instead of a file per partition.
        heatflow_block = ''
        if Elmer_thermal_boundaryconditions:
            items = ''
            for n, thermal_bc in enumerate(Elmer_thermal_boundaryconditions):
                items += (f'  Variable {n+1} = Temperature Loads\n'
                          f'  Operator {n+1} = boundary sum\n'
                          f'  Mask Name {n+1} = String "{heatflow_mask(thermal_bc)}"\n')
            heatflow_block = f'''
Solver {{n}}
  Equation = SaveHeatFlow
  Procedure = "SaveData" "SaveScalars"
  Filename = "../thermal_heatflow.dat"
  Parallel Reduce = Logical True
{items}End
'''

        # Heat flux and temperature gradient, opt-in. The gradient of a linear element is constant in the element, and
        # at a material interface the gradient jumps by the conductivity ratio (the normal heat flux is continuous, the
        # tangential flux jumps the other way). So the flux solver computes them per element (Discontinuous Galerkin),
        # and the output averages them within each body: nodes on an interface get one value per body. Averaging at
        # the nodes across bodies instead smears these jumps over several microns (tested on the thermal example:
        # the gradient in Si next to the oxide 17x too high). This needs ResultOutputSolver (Discontinuous Bodies)
        # instead of Post File; the files keep their names.
        flux_blocks = []
        if heat_flux_output:
            flux_blocks.append('''
Solver {n}
  Equation = "HeatFlux"
  Procedure = "FluxSolver" "FluxSolver"
  Target Variable = Temperature
  Flux Coefficient = "Heat Conductivity"
  Calculate Flux = Logical True
  Calculate Grad = Logical True
  Discontinuous Galerkin = Logical True
  Linear System Solver = Iterative
  Linear System Iterative Method = CG
  Linear System Preconditioning = ILU0
  Linear System Max Iterations = 2000
  Linear System Convergence Tolerance = 1.0e-10
End
''')
            flux_blocks.append('''
Solver {n}
  Exec Solver = After Simulation
  Equation = "ResultOutput"
  Procedure = "ResultOutputSolve" "ResultOutputSolver"
  Output File Name = "../thermal_results"
  Vtu Format = Logical True
  Discontinuous Bodies = Logical True
  Save Geometry Ids = Logical True
End
''')

        extra_blocks = ([heatflow_block] if heatflow_block else []) + flux_blocks
        extra_solvers = ''.join(block.format(n=3 + i) for i, block in enumerate(extra_blocks))
        n_solvers = 2 + len(extra_blocks)
        active_solvers = f'Active Solvers({n_solvers}) = ' + ' '.join(str(i) for i in range(1, n_solvers + 1))
        post_file_line = '' if heat_flux_output else f'Post File = {vtu_file}\n'

        header1=f'''
Check Keywords "warn"

Header
Mesh DB "mesh" "."
End

Simulation
Coordinate Mapping(3) = Integer 1 2 3
Simulation Type = Steady state
Steady State Max Iterations = 1
Coordinate System = String "Cartesian"
Coordinate Scaling = Real 1e-6
Use Mesh Names = Logical True
Mesh Levels = 1
{post_file_line}End


Equation 1
Name = "ThermalPhysics"
{active_solvers}
End

Solver 1
Equation = Heat Equation
Procedure = "HeatSolve" "HeatSolver"
Variable = Temperature
Calculate Loads = Logical True
{linear_system_block}
Steady State Convergence Tolerance = 1.0e-5
End

Solver 2
  Equation = SaveScalars
  Procedure = "SaveData" "SaveScalars"

  Filename = "../thermal_results.dat"
  Parallel Reduce = Logical True

  Variable 1 = Temperature
  Operator 1 = min
  Operator 2 = max
End
{extra_solvers}'''

        f.write(header1 + "\n")


        # write Material sections
        for n,material in enumerate(Elmer_materials):
            item = f'Material {n+1}\n   Name = string "{material["name"]}"\n'
            # thermal conductivity can be single value or table passed as string here
            item = item + f'   Density = Real {material["density"]}\n'
            # a direction-dependent conductivity is a diagonal tensor: Heat Conductivity(3) = kx ky kz
            keyword = 'Heat Conductivity(3)' if material.get("thermalcond_size") == 3 else 'Heat Conductivity'
            item = item + f'   {keyword} = {material["thermalcond"]}\n'
            item = item + "End\n"
            f.write(item + "\n")

        # write Bodies sections
        for n,body in enumerate(Elmer_bodies):
            item = f'Body {n+1}\n   Equation = Integer 1\n'
            item = item + f'   Name = "{body["name"]}"\n'
            item = item + f'   Material = {body["material"]}\n'

            if "bodyforce_number" in body.keys():
                item = item + f'   Body Force = {body["bodyforce_number"]}\n'
            if start_temp is not None:
                item = item + '   Initial Condition = 1\n'

            item = item + "End\n"
            f.write(item + '\n')

        if start_temp is not None:
            f.write(f'Initial Condition 1\n   Temperature = Real {start_temp:2f}\nEnd\n\n')

        # write thermal power for heat source
        for n,power in enumerate(Elmer_body_forces):
            item = f'Body Force {n+1}\n'
            item = item + f'   Volumetric Heat Source = -distribute {power:2e}\n'
            item = item + "End\n"
            f.write(item + '\n')

        # write thermal boundary conditions
        for n,thermal_bc in enumerate(Elmer_thermal_boundaryconditions):
            item = f'Boundary Condition {n+1}\n'
            item = item + f'   Name = "{thermal_bc["name"]}"\n'
            item = item + f'   Temperature = Real {thermal_bc["temp"]:2f}\n'
            item = item + f'   {heatflow_mask(thermal_bc)} = Logical True\n'
            item = item + "End\n"
            f.write(item + '\n')


def heatflow_mask(thermal_bc):
    """SaveScalars mask of a constant-temperature boundary, for its heat flow. It also names the column in
    thermal_heatflow.dat.names ("... over bc heatflow_constanttemp_202")."""
    return f'heatflow_{thermal_bc["name"]}'


#------------------------- mesh conversion *.msh to Elmer mesh -------------------------

def clear_directory (path):
    # clear mesh directory, but skip files if locked
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            try:
                os.remove(os.path.join(root, name))
            except (PermissionError, OSError):
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except (PermissionError, OSError):
                pass    


def convert_mesh_to_elmer (input_mesh, ELMER_MPI_THREADS=1):
    # convert gmsh mesh *.msh to Elmer mesh
    # mesh name is: msh_name
    # mesh directory is: sim_path
    # ElmerGrid.exe 14 2 <*.msh> -autoclean -out <meshdir>

    input_mesh_path = os.path.dirname(input_mesh)
    elmer_mesh_path = os.path.join(input_mesh_path, 'mesh' )

    # clear target mesh directory first, to remove old mesh fragments
    clear_directory(elmer_mesh_path)

    # ElmerGrid: from ELMER_HOME (Windows installer), else from the PATH. Without it, the model files are
    # still written, only the mesh conversion is skipped (before, a missing ElmerGrid or ELMER_HOME crashed here)
    ElmerGrid = ""
    Elmer_home = os.environ.get("ELMER_HOME")
    if Elmer_home:
        candidate = os.path.join(Elmer_home, "bin", "ElmerGrid.exe" if platform.system() == "Windows" else "ElmerGrid")
        if os.path.isfile(candidate):
            ElmerGrid = candidate
    if ElmerGrid == "":
        ElmerGrid = shutil.which("ElmerGrid") or ""

    
    if ElmerGrid != "":
        print ('Convert mesh to Elmer format')

        # Command as a list of arguments
        cmd = [
            ElmerGrid,
            "14",
            "2",
            input_mesh.replace('\\','/'),
            "-autoclean",
            "-out",
            elmer_mesh_path.replace('\\','/')
        ]

        run_elmergrid(cmd, f"converting {input_mesh} to an Elmer mesh")

        # Second step if we use multithreading: modify the mesh again
        if ELMER_MPI_THREADS>1:
            print (f'Split mesh now for MPI multithreading with {ELMER_MPI_THREADS} threads')

            # Command as a list of arguments
            # ElmerGrid 2 2 mesh -metiskway MPI_threads
            cmd = [
                ElmerGrid,
                "2",
                "2",
                elmer_mesh_path.replace('\\','/'),
                "-partdual",
                "-metiskway",
                str(int(ELMER_MPI_THREADS))
            ]

            print(cmd)
            run_elmergrid(cmd, f"splitting the Elmer mesh into {ELMER_MPI_THREADS} partitions")

    else:
        print('ElmerGrid not found (set ELMER_HOME or put ElmerGrid on the PATH), the mesh was not converted '
              'to Elmer format. Run: ElmerGrid 14 2 <model>.msh -autoclean -out mesh')


def run_elmergrid (cmd, what):
    """Run ElmerGrid and print its output; stop if it fails. Without this check a crashed ElmerGrid (e.g. a
    segmentation fault on a large gmsh mesh) went unnoticed until ElmerSolver reported a missing mesh folder."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("STDOUT:\n", result.stdout)
    if len(result.stderr)>0:
        print("STDERR:\n", result.stderr)
    if result.returncode != 0:
        print(f"ERROR: ElmerGrid failed {what} (exit code {result.returncode}), no usable Elmer mesh was written.")
        exit(1)


def get_ELMER_MPI_THREADS (settings):
    # optional multithreading for Elmer FEM because it requires modifies settings in case.sif file
    ELMER_MPI_THREADS = settings.get('ELMER_MPI_THREADS', None)
    if ELMER_MPI_THREADS is not None:
        print(f'MPI multithreading specified in model file, ELMER_MPI_THREADS={ELMER_MPI_THREADS}')
    else:
        print(f'MPI multithreading disabled: settings["ELMER_MPI_THREADS"] not set in model code')
        ELMER_MPI_THREADS = 1
    print("ELMER_MPI_THREADS =", ELMER_MPI_THREADS)
    return ELMER_MPI_THREADS    


