use std::{sync::Arc, format};

use codemp::prelude::*;
use codemp::errors::Error as CodempError;

use pyo3::{
    prelude::*,
    exceptions::{PyConnectionError, PyRuntimeError, PyBaseException}, 
    types::PyString,
};

struct PyCodempError(CodempError);
impl From::<CodempError> for PyCodempError {
    fn from(err: CodempError) -> Self {
        PyCodempError(err)
    }
}

impl From<PyCodempError> for PyErr {
    fn from(err: PyCodempError) -> PyErr {
        match err.0 {
            CodempError::Transport { status, message } => {
                PyConnectionError::new_err(format!("Transport error: ({}) {}", status, message))
            }
            CodempError::Channel { send } => {
                PyConnectionError::new_err(format!("Channel error (send:{})", send))
            },
            CodempError::InvalidState { msg } => {
                PyRuntimeError::new_err(format!("Invalid state: {}", msg))
            },
            CodempError::Deadlocked => {
                PyRuntimeError::new_err(format!("Deadlock, retry."))
            },
            CodempError::Filler { message } => {
                PyBaseException::new_err(format!("Generic error: {}", message))
            }
        }
    }
}

#[pyfunction]
fn codemp_init<'a>(py: Python<'a>) -> PyResult<Py<PyClientHandle>> {
    let py_instance: PyClientHandle = CodempInstance::default().into();
    Ok(Py::new(py, py_instance)?)
}

#[pyclass]
struct PyClientHandle(Arc<CodempInstance>);

impl From::<CodempInstance> for PyClientHandle {
    fn from(value: CodempInstance) -> Self {
        PyClientHandle(Arc::new(value))
    }
}

#[pymethods]
impl PyClientHandle {

    fn connect<'a>(&'a self, py: Python<'a>, addr: String) ->PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            rc.connect(addr.as_str())
                .await
                .map_err(PyCodempError::from)?;
            Ok(())
        })
    }

    // join a workspace
    fn join<'a>(&'a self, py: Python<'a>, session: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let curctrl: PyCursorController = rc.join(session.as_str())
                .await
                .map_err(PyCodempError::from)?
                .into();

            Python::with_gil(|py| {
                Ok(Py::new(py, curctrl)?)
            })
        })
    }

    fn create<'a>(&'a self, py: Python<'a>, path: String, content: Option<String>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            rc.create(path.as_str(), content.as_deref())
                .await
                .map_err(PyCodempError::from)?;
            Ok(())
        })
    }

    fn attach<'a>(&'a self, py: Python<'a>, path: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let buffctrl: PyBufferController = rc.attach(path.as_str())
                .await
                .map_err(PyCodempError::from)?
                .into();

            Python::with_gil(|py| {
                Ok(Py::new(py, buffctrl)?)
            })
        })
    }
    
    fn get_cursor<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let curctrl: PyCursorController = rc.get_cursor()
                .await
                .map_err(PyCodempError::from)?
                .into();

            Python::with_gil(|py| {
                Ok(Py::new(py, curctrl)?)
            })
        })
    }

    fn get_buffer<'a>(&'a self, py: Python<'a>, path: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let buffctrl: PyBufferController = rc.get_buffer(path.as_str())
                .await
                .map_err(PyCodempError::from)?
                .into();

            Python::with_gil(|py| {
                Ok(Py::new(py, buffctrl)?)
            })
        })
    }

    fn leave_workspace<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            rc.leave_workspace()
                .await
                .map_err(PyCodempError::from)?;
            Ok(())
        })
    }

    fn disconnect_buffer<'a>(&'a self, py: Python<'a>, path: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            rc.disconnect_buffer(path.as_str())
                .await
                .map_err(PyCodempError::from)?;
            Ok(())
        })
    }

    fn select_buffer<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let cont = rc.select_buffer()
                .await
                .map_err(PyCodempError::from)?;

            Ok(cont)
        })
    }
}


/* ########################################################################### */

#[pyclass]
struct PyCursorController(Arc<CodempCursorController>);

impl From::<Arc<CodempCursorController>> for PyCursorController {
    fn from(value: Arc<CodempCursorController>) -> Self {
        PyCursorController(value)
    }
}

#[pymethods]
impl PyCursorController {

    fn send<'a>(&'a self, path: String, start: (i32, i32), end: (i32, i32)) -> PyResult<()> {
        let pos = CodempCursorPosition {
            buffer: path,
            start: Some(start.into()),
            end: Some(end.into())
        };

        Ok(self.0.send(pos).map_err(PyCodempError::from)?)
    }

    fn try_recv(&self, py: Python<'_>) -> PyResult<PyObject> {
        match self.0.try_recv().map_err(PyCodempError::from)? {
            Some(cur_event) => {
                let evt = PyCursorEvent::from(cur_event);
                Ok(evt.into_py(py))
            },
            None => Ok(py.None())
        }
    }

    fn recv<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let cur_event: PyCursorEvent = rc.recv()
                .await
                .map_err(PyCodempError::from)?
                .into();
            Python::with_gil(|py| {
                Ok(Py::new(py, cur_event)?)
            })
        })
    }

    fn poll<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            Ok(rc.poll().await.map_err(PyCodempError::from)?)
        })
    }
}

#[pyclass]
struct PyBufferController(Arc<CodempBufferController>);

impl From::<Arc<CodempBufferController>> for PyBufferController {
    fn from(value: Arc<CodempBufferController>) -> Self { 
        PyBufferController(value)
    }
}

#[pymethods]
impl PyBufferController {

    fn content<'a>(&self, py: Python<'a>) -> &'a PyString {
        PyString::new(py, self.0.content().as_str())
    }

    fn send(&self, start: usize, end: usize, txt: String) -> PyResult<()>{
        let op = CodempTextChange { 
            span: start..end,
            content: txt.into() 
        };
        Ok(self.0.send(op).map_err(PyCodempError::from)?)
    }

    fn try_recv(&self, py: Python<'_>) -> PyResult<PyObject> {
        match self.0.try_recv().map_err(PyCodempError::from)? {
            Some(txt_change) => {
                let evt = PyTextChange::from(txt_change);
                Ok(evt.into_py(py))
            },
            None => Ok(py.None())
        }
    }

    fn recv<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let txt_change: PyTextChange = rc.recv()
                .await
                .map_err(PyCodempError::from)?
                .into();
            Python::with_gil(|py| {
                Ok(Py::new(py, txt_change)?)
            })
        })
    }

    fn poll<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            Ok(rc.poll().await.map_err(PyCodempError::from)?)
        })
    }
}

/* ---------- Type Wrappers ----------*/
// All these objects are not meant to be handled rust side.
// Just to be sent to the python heap.

#[pyclass]
struct PyCursorEvent {
    #[pyo3(get, set)]
    user: String,
    
    #[pyo3(get, set)]
    buffer: String,
    
    #[pyo3(get, set)]
    start: (i32, i32),

    #[pyo3(get, set)]
    end: (i32, i32)
}

impl From<CodempCursorEvent> for PyCursorEvent {
    fn from(value: CodempCursorEvent) -> Self {
        // todo, handle this optional better?
        let pos = value.position.unwrap_or_default();
        PyCursorEvent {
            user: value.user,
            buffer: pos.buffer,
            start: pos.start.unwrap_or_default().into(),
            end: pos.end.unwrap_or_default().into()
        }
    }
}

#[pyclass]
struct PyTextChange {
    #[pyo3(get, set)]
    start_incl: usize,
    
    #[pyo3(get, set)]
    end_excl: usize,

    #[pyo3(get, set)]
    content: String
}

impl From<CodempTextChange> for PyTextChange {
    fn from(value: CodempTextChange) -> Self {
        PyTextChange { start_incl: value.span.start, end_excl: value.span.end, content: value.content }
    }
}

/* ------ Python module --------*/
#[pymodule]
fn codemp_client(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(codemp_init, m)?)?;
    m.add_class::<PyClientHandle>()?;
    m.add_class::<PyCursorController>()?;
    m.add_class::<PyBufferController>()?;

    m.add_class::<PyCursorEvent>()?;
    m.add_class::<PyTextChange>()?;

    Ok(())
}


