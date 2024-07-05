"""
Main interface module to use pyEPR.

Contains code to connect to Ansys and to analyze HFSS files using the EPR method.

This module handles the microwave part of the analysis and connection to

Further contains code to be able to do autogenerated reports,

Copyright Zlatko Minev, Zaki Leghtas, and the pyEPR team
2015, 2016, 2017, 2018, 2019, 2020
"""

from __future__ import print_function  # Python 2.7 and 3 compatibility

import sys
from pathlib import Path

import pandas as pd

from . import Dict, ansys, config, logger
from .toolbox.pythonic import get_instance_vars

diss_opt = [
    'dielectrics_bulk', 'dielectric_surfaces', 'resistive_surfaces', 'seams'
]


class ProjectInfo(object):
    """
    Primary class to store interface information between ``pyEPR`` and ``Ansys``.

    * **Ansys:** stores and provides easy access to the ansys interface classes :py:class:`pyEPR.ansys.HfssApp`,
      :py:class:`pyEPR.ansys.HfssDesktop`, :py:class:`pyEPR.ansys.HfssProject`, :py:class:`pyEPR.ansys.HfssDesign`,
      :py:class:`pyEPR.ansys.HfssSetup` (which, if present could nbe a subclass, such as a driven modal setup
      :py:class:`pyEPR.ansys.HfssDMSetup`, eigenmode :py:class:`pyEPR.ansys.HfssEMSetup`, or Q3D  :py:class:`pyEPR.ansys.AnsysQ3DSetup`),
      the 3D modeler to design geometry :py:class:`pyEPR.ansys.HfssModeler`.
    * **Junctions:** The class stores params about the design that the user puts will use, such as the names and
      properties of the junctions, such as which rectangle and line is associated with which junction.


    Note:

        **Junction parameters.**
        The junction parameters are stored in the ``self.junctions`` ordered dictionary

        A Josephson tunnel junction has to have its parameters specified here for the analysis.
        Each junction is given a name and is specified by a dictionary.
        It has the following properties:

        * ``Lj_variable`` (str):
                Name of HFSS variable that specifies junction inductance Lj defined
                on the boundary condition in HFSS.
                WARNING: DO NOT USE Global names that start with $.
        * ``rect`` (str):
                String of Ansys name of the rectangle on which the lumped boundary condition is defined.
        * ``line`` (str):
                Name of HFSS polyline which spans the length of the rectangle.
                Used to define the voltage across the junction.
                Used to define the current orientation for each junction.
                Used to define sign of ZPF.
        * ``length`` (str):
                Length in HFSS of the junction rectangle and line (specified in meters).
                To create, you can use :code:`epr.parse_units('100um')`.
        * ``Cj_variable`` (str, optional) [experimental]:
                Name of HFSS variable that specifies junction inductance Cj defined
                on the boundary condition in HFSS. DO NOT USE Global names that start with ``$``.

    Warning:

        To define junctions, do **NOT** use global names!
        I.e., do not use names in ansys that start with ``$``.


    Note:

        **Junction parameters example .** To define junction parameters, see the following example

        .. code-block:: python
            :linenos:

            # Create project infor class
            pinfo = ProjectInfo()

            # Now, let us add a junction called `j1`, with the following properties
            pinfo.junctions['j1'] = {
                        'Lj_variable' : 'Lj_1', # name of Lj variable in Ansys
                        'rect'        : 'jj_rect_1',
                        'line'        : 'jj_line_1',
                        #'Cj'          : 'Cj_1' # name of Cj variable in Ansys - optional
                        }

        To extend to define 5 junctions in bulk, we could use the following script

        .. code-block:: python
            :linenos:

            n_junctions = 5
            for i in range(1, n_junctions + 1):
                pinfo.junctions[f'j{i}'] = {'Lj_variable' : f'Lj_{i}',
                                            'rect'        : f'jj_rect_{i}',
                                            'line'        : f'jj_line_{i}'}


    .. _Google Python Style Guide:
        http://google.github.io/styleguide/pyguide.html

    """
    class _Dissipative:
        """
        Deprecating the _Dissipative class and turning it into a dictionary.
        This is used to message people on the deprecation so they could change their scripts.
        """
        def __init__(self):
            self['pinfo'] = None
            for opt in diss_opt:
                self[opt] = None

        def __setitem__(self, key, value):
            # --- check valid inputs ---
            if not (key in diss_opt or key == 'pinfo'):
                raise ValueError(f"No such parameter {key}")
            if key != 'pinfo' and (not isinstance(value, (list, dict)) or \
                    not all(isinstance(x, str) for x in value)) and (value != None):
                raise ValueError(f'dissipative[\'{key}\'] must be a list of strings ' \
                    'containing names of models in the project or dictionary of strings of models containing ' \
                    'material loss properties!'
                )
            if key != 'pinfo' and hasattr(self['pinfo'], 'design'):
                for x in value:
                    if x not in self['pinfo'].get_all_object_names():
                        raise ValueError(
                            f'\'{x}\' is not an object in the HFSS project')
            super().__setattr__(key, value)

        def __getitem__(self, attr):
            if not (attr in diss_opt or attr == 'pinfo'):
                raise AttributeError(f'dissipative has no attribute "{attr}". '\
                    f'The possible attributes are:\n {str(diss_opt)}')
            return super().__getattribute__(attr)

        def __setattr__(self, attr, value):
            logger.warning(
                f"DEPRECATED!! use pinfo.dissipative['{attr}'] = {value} instead!"
            )
            self[attr] = value

        def __getattr__(self, attr):
            raise AttributeError(f'dissipative has no attribute "{attr}". '\
                f'The possible attributes are:\n {str(diss_opt)}')

        def __getattribute__(self, attr):
            if attr in diss_opt:
                logger.warning(
                    f"DEPRECATED!! use pinfo.dissipative['{attr}'] instead!")
            return super().__getattribute__(attr)

        def __repr__(self):
            return str(self.data())

        def data(self):
            """Return dissipative as dictionary"""
            return {str(opt): self[opt] for opt in diss_opt}

    def __init__(self,
                project_path: str = None,
                project_name: str = None,
                design_name: str = None,
                setup_name: str = None,
                dielectrics_bulk: list =None,
                dielectric_surfaces: list = None,
                resistive_surfaces: list= None,
                seams: list= None,
                do_connect: bool = True):
        """
        Keyword Arguments:

            project_path (str) : Directory path to the hfss project file.
                Should be the directory, not the file.
                Defaults to ``None``; i.e., assumes the project is open, and thus gets the project based
                on `project_name`.
            project_name (str) : Name of the project within the project_path.
                Defaults to ``None``, which will get the current active one.
            design_name  (str) : Name of the design within the project.
                Defaults to ``None``, which will get the current active one.
            setup_name  (str) :  Name of the setup within the design.
                Defaults to ``None``, which will get the current active one.
            dielectrics_bulk (list(str)) : List of names of dielectric bulk objects.
                Defaults to ``None``.
            dielectric_surfaces (list(str)) : List of names of dielectric surfaces.
                Defaults to ``None``.
            resistive_surfaces (list(str)) : List of names of resistive surfaces.
                Defaults to ``None``.
            seams (list(str)) : List of names of seams.
                Defaults to ``None``.
            do_connect (bool) [additional]: Do create connection to Ansys or not? Defaults to ``True``.
        
        """

        # Path: format path correctly to system convention
        self.project_path = str(Path(project_path)) \
            if not (project_path is None) else None
        self.project_name = project_name
        self.design_name = design_name
        self.setup_name = setup_name

        # HFSS design: describe junction parameters
        # TODO: introduce modal labels
        self.junctions = Dict()  # See above for help
        self.ports = Dict()

        # Dissipative HFSS volumes and surfaces
        self.dissipative = self._Dissipative()
        for opt in diss_opt:
            self.dissipative[opt] = locals()[opt]
        self.options = config.ansys

        # Connected to HFSS variable
        self.app = None
        self.desktop = None
        self.project = None
        self.design = None
        self.setup = None

        if do_connect:
            self.connect()
            self.dissipative['pinfo'] = self

    _Forbidden = [
        'app', 'design', 'desktop', 'project', 'dissipative', 'setup',
        '_Forbidden', 'junctions'
    ]

    def save(self):
        '''
        Return all the data in a dictionary form that can be used to be saved
        '''
        return dict(
            pinfo=pd.Series(get_instance_vars(self, self._Forbidden)),
            dissip=pd.Series(self.dissipative.data()),
            options=pd.Series(get_instance_vars(self.options), dtype='object'),
            junctions=pd.DataFrame(self.junctions),
            ports=pd.DataFrame(self.ports),
        )

    def connect_project(self):
        """Sets 
        self.app
        self.desktop
        self.project
        self.project_name
        self.project_path 
        """
        logger.info('Connecting to Ansys Desktop API...')

        self.app, self.desktop, self.project = ansys.load_ansys_project(
            self.project_name, self.project_path)

        if self.project:
            # TODO: should be property?
            self.project_name = self.project.name
            self.project_path = self.project.get_path()

    def connect_design(self, design_name: str = None):
        """Sets
        self.design
        self.design_name
        """
        if design_name is not None:
            self.design_name = design_name

        designs_in_project = self.project.get_designs()
        if not designs_in_project:
            self.design = None
            logger.info(
                f'No active design found (or error getting active design).')
            return

        if self.design_name is None:
            # Look for the active design
            try:
                self.design = self.project.get_active_design()
                self.design_name = self.design.name
                logger.info(
                    '\tOpened active design\n'
                    f'\tDesign:    {self.design_name} [Solution type: {self.design.solution_type}]'
                )
            except Exception as e:
                # No active design
                self.design = None
                self.design_name = None
                logger.info(
                    f'No active design found (or error getting active design). Note: {e}'
                )
        else:

            try:
                self.design = self.project.get_design(self.design_name)
                logger.info(
                    '\tOpened active design\n'
                    f'\tDesign:    {self.design_name} [Solution type: {self.design.solution_type}]'
                )

            except Exception as e:
                _traceback = sys.exc_info()[2]
                logger.error(f"Original error \N{loudly crying face}: {e}\n")
                raise (Exception(' Did you provide the correct design name?\
                    Failed to pull up design. \N{loudly crying face}').
                       with_traceback(_traceback))

    def connect_setup(self):
        """Connect to the first available setup or create a new in eigenmode and driven modal

        Raises:
            Exception: [description]
        """
        # Setup
        if self.design is not None:
            try:
                setup_names = self.design.get_setup_names()

                if len(setup_names) == 0:
                    logger.warning('\tNo design setup detected.')
                    setup = None
                    if self.design.solution_type == 'Eigenmode':
                        logger.warning('\tCreating eigenmode default setup.')
                        setup = self.design.create_em_setup()
                    elif self.design.solution_type == 'DrivenModal':
                        logger.warning('\tCreating driven modal default setup.')
                        setup = self.design.create_dm_setup()
                    elif self.design.solution_type == 'DrivenTerminal':
                        logger.warning('\tCreating driven terminal default setup.')
                        setup = self.design.create_dt_setup()
                    elif self.design.solution_type == 'Q3D':
                        logger.warning('\tCreating Q3D default setup.')
                        setup = self.design.create_q3d_setup()
                    self.setup_name = setup.name
                elif self.setup_name is None:
                    self.setup_name = setup_names[0]
                    logger.warning(f"no setup name was specified, will use the first setup '{self.setup_name}'")

                # get the actual setup if there is one
                self.get_setup(self.setup_name)

            except Exception as e:

                _traceback = sys.exc_info()[2]
                logger.error(f"Original error \N{loudly crying face}: {e}\n")
                raise Exception(' Did you provide the correct setup name?\
                            Failed to pull up setup. \N{loudly crying face}'
                                ).with_traceback(_traceback)

        else:
            self.setup = None
            self.setup_name = None

    def connect(self):
        """
        Do establish connection to Ansys desktop.
        Connects to project and then get design and setup
        """

        self.connect_project()
        if not self.project:
            logger.info('\tConnection to Ansys NOT established.  \n')
        if self.project:
            try:
                self.connect_design()
            except Exception as e:
                print(e)
                self.project.release()
                self.desktop.release()
                self.app.release()
                ansys.release()
        self.connect_setup()

        # Finalize
        if self.project:
            self.project_name = self.project.name
        if self.design:
            self.design_name = self.design.name

        if self.project and self.design:
            logger.info(
                f'\tConnected to project \"{self.project_name}\" and design \"{self.design_name}\" \N{grinning face} \n'
            )

        if not self.project:
            logger.info(
                '\t Project not detected in Ansys. Is there a project in your desktop app? \N{thinking face} \n'
            )

        if not self.design:
            logger.info(
                f'\t Connected to project \"{self.project_name}\". No design detected'
            )

        return self

    def get_setup(self, name: str):
        """
        Connects to a specific setup for the design.
        Sets  self.setup and self.setup_name.

        Args:
            name (str): Name of the setup.
            If the setup does not exist, then throws a logger error.
            Defaults to ``None``, in which case returns None

        """
        if name is None:
            return None
        self.setup = self.design.get_setup(name=name)
        if self.setup is None:
            logger.error(f"Could not retrieve setup: {name}\n \
                        Did you give the right name? Does it exist?")

        self.setup_name = self.setup.name
        logger.info(
            f'\tOpened setup `{self.setup_name}`  ({type(self.setup)})')
        return self.setup

    def check_connected(self):
        """
        Checks if fully connected including setup.
        """
        return\
            (self.setup is not None) and\
            (self.design is not None) and\
            (self.project is not None) and\
            (self.desktop is not None) and\
            (self.app is not None)

    def disconnect(self):
        '''
        Disconnect from existing Ansys Desktop API.
        '''
        assert self.check_connected() is True,\
            "It does not appear that you have connected to HFSS yet.\
            Use the connect()  method. \N{nauseated face}"

        self.project.release()
        self.desktop.release()
        self.app.release()
        ansys.release()

    # UTILITY FUNCTIONS

    def get_dm(self):
        '''
        Utility shortcut function to get the design and modeler.

        .. code-block:: python

            oDesign, oModeler = pinfo.get_dm()

        '''
        return self.design, self.design.modeler

    def get_all_variables_names(self):
        """Returns array of all project and local design names."""
        return self.project.get_variable_names(
        ) + self.design.get_variable_names()

    def get_all_object_names(self):
        """Returns array of strings"""
        o_objects = []
        for s in ["Non Model", "Solids", "Unclassified", "Sheets", "Lines"]:
            o_objects += self.design.modeler.get_objects_in_group(s)
        return o_objects

    def validate_junction_info(self):
        """Validate that the user has put in the junction info correctly.
        Do not also forget to check the length of the rectangles/line of
        the junction if you change it.
        """

        all_variables_names = self.get_all_variables_names()
        all_object_names = self.get_all_object_names()

        for jjnm, jj in self.junctions.items():

            assert jj['Lj_variable'] in all_variables_names,\
                """pyEPR ProjectInfo user error found \N{face with medical mask}:
                Seems like for junction `%s` you specified a design or project
                variable for `Lj_variable` that does not exist in HFSS by the name:
                 `%s` """ % (jjnm, jj['Lj_variable'])

            for name in ['rect', 'line']:

                assert jj[name] in all_object_names, \
                    """pyEPR ProjectInfo user error found \N{face with medical mask}:
                    Seems like for junction `%s` you specified a %s that does not exist
                    in HFSS by the name: `%s` """ % (jjnm, name, jj[name])

    def __del__(self):
        logger.info('Disconnected from Ansys HFSS')
        # self.disconnect()
