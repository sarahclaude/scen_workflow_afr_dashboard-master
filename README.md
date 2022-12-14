# scen_workflow_afr_dashboard

## Purpose

- This code is a web application that ca be used to generate various diagrams, maps and data tables. This facilitates
  the interpretation of climate data and promotes reflection and exchange between team members. The application can be
  used locally, using streamlit.io server or using a Jupyter Notebook. Note that the Jupyter entry point is no longer
  maintained since v1.4.0.
- The code also holds the object-oriented structure that is common between projects scen_workflow_afr and dashboard. It
  defines the attributes and behaviour of several objects such as climate variables/indices and emissions scenarios.
- Climate data can be stored at 3 differents locations : on a local hard drive, streamlit server, or Google Drive. Note
  that the 3rd option needs further developement to be faster. The current approach involves a scan of the Google and
  local drives, which can take longer if using the application with a slow internet connection.   

## Notes

Technical documentation can be found [here](https://github.com/Ouranosinc/scen_workflow_afr/doc).

## Releases

### v1.4.0

Implemented features:
- initial version : time series, maps, tables of statistics, cluster table and plot.

### v1.4.1

Implemented features:
- added a streamlit-based access control in which users can be associated with one or several projects;
- added an opption to store the climate data used by the portal on Google Drive (a little bit slow, but usable).

### v1.4.2

Implemented features:
- added an option to generate Taylor diagrams (see the keywords starting wiith 'opt_taylor'). In the case of climate
  variables, a first diagram is generated for the simulation (prior to bias adjustement) while a second diagram is 
  generated for the scenario (after bias adjustment). In the case of climate indices, a single diagram is generated.  

## Contributing

This is a development project that is being used in production by climate services specialists. If you're interested in
being involved in the development, want to suggest features or report bugs, please leave us a message on the
[issue tracker](https://github.com/Ouranosinc/scen_workflow_afr_dashboard/issues).