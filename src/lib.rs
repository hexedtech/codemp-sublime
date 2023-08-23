use std::{sync::Arc, format};

use codemp::{prelude::*};
use codemp::errors::Error as CodempError;

use pyo3::{
    prelude::*,
    exceptions::{PyConnectionError, PyRuntimeError, PyBaseException}, 
    types::PyString
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
            CodempError::Filler { message } => {
                PyBaseException::new_err(format!("Generic error: {}", message))
            }
        }
    }
}

#[pyfunction]
fn codemp_init<'a>(py: Python<'a>) -> PyResult<Py<PyClientHandle>> {
    let py_instance: PyClientHandle = CodempInstance::default().into();
    Python::with_gil(|py| {
        Ok(Py::new(py, py_instance)?)
    })
}

#[pyclass]
#[derive(Clone)]
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
            rc.connect(addr.as_str()).await.map_err(PyCodempError::from)?;
            Ok(())
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
            let buffctrl = rc.attach(path.as_str())
                .await
                .map_err(PyCodempError::from)?;

            Python::with_gil(|py| {
                Ok(Py::new(py, PyBufferController(buffctrl))?)
            })
        })
    }

    fn join<'a>(&'a self, py: Python<'a>, session: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let curctrl = rc.join(session.as_str())
                .await
                .map_err(PyCodempError::from)?;

            Python::with_gil(|py| {
                Ok(Py::new(py, PyCursorController(curctrl))?)
            })
        })
    }
    
    fn get_cursor<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let curctrl = rc.get_cursor()
                .await
                .map_err(PyCodempError::from)?;

            Python::with_gil(|py| {
                Ok(Py::new(py, PyCursorController(curctrl))?)
            })
        })
    }

    fn get_buffer<'a>(&'a self, py: Python<'a>, path: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let buffctrl = rc.get_buffer(path.as_str())
                .await
                .map_err(PyCodempError::from)?;

            Python::with_gil(|py| {
                Ok(Py::new(py, PyBufferController(buffctrl))?)
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
}

impl From::<CodempCursorController> for PyCursorController {
    fn from(value: CodempCursorController) -> Self {
        PyCursorController(Arc::new(value))
    }
}

impl From::<CodempBufferController> for PyBufferController {
    fn from(value: CodempBufferController) -> Self { 
        PyBufferController(Arc::new(value))
    }
}

#[pyclass]
struct PyCursorController(Arc<CodempCursorController>);

#[pymethods]
impl PyCursorController {
    // fn callback<'a>(&'a self, py: Python<'a>, coro_py: Py<PyAny>, caller_id: Py<PyString>) -> PyResult<&'a PyAny> {
    //     let mut rc = self.0.clone();
    //     let cb = coro_py.clone();
    //     // We want to start polling the ControlHandle and call the callback every time
    //     // we have something.

    //     pyo3_asyncio::tokio::future_into_py(py, async move {
    //         while let Some(op) = rc.poll().await {
    //             let start = op.start.unwrap_or(Position { row: 0, col: 0});
    //             let end = op.end.unwrap_or(Position { row: 0, col: 0});

    //             let cb_fut = Python::with_gil(|py| -> PyResult<_> {
    //                 let args = (op.user, caller_id.clone(), op.buffer, (start.row, start.col), (end.row, end.col));
    //                 let coro = cb.call1(py, args)?;
    //                 pyo3_asyncio::tokio::into_future(coro.into_ref(py))
    //             })?;

    //             cb_fut.await?;
    //         }
    //         Ok(())
    //     })
    // }

    fn send<'a>(&'a self, py: Python<'a>, path: String, start: (i32, i32), end: (i32, i32)) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();
        let pos = CodempCursorPosition {
            buffer: path,
            start: Some(CodempRowCol { row: start.0, col: start.1 }),
            end: Some(CodempRowCol { row: end.0, col: end.1 })
        };

        pyo3_asyncio::tokio::future_into_py(py, async move {
            rc.send(pos)
                .map_err(PyCodempError::from)?;
            Ok(())
        })

    }

    fn recv<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let cur_event = rc.recv()
                .await
                .map_err(PyCodempError::from)?;
            Ok(())
        })
    }
}
#[pyclass]
struct PyBufferController(Arc<CodempBufferController>);

#[pymethods]
impl PyBufferController {
    // fn callback<'a>(&'a self, py: Python<'a>, coro_py: Py<PyAny>, caller_id: Py<PyString>) -> PyResult<&'a PyAny> {
    //     let mut rc = self.0.clone();
    //     let cb = coro_py.clone();
    //      // We want to start polling the ControlHandle and call the callback every time
    //      // we have something.

    //     pyo3_asyncio::tokio::future_into_py(py, async move {
    //         while let Some(edit) = rc.poll().await {
    //             let start = edit.span.start;
    //             let end = edit.span.end;
    //             let text = edit.content;

    //             let cb_fut = Python::with_gil(|py| -> PyResult<_> {
    //                 let args = (caller_id.clone(), start, end, text);
    //                 let coro = cb.call1(py, args)?;
    //                 pyo3_asyncio::tokio::into_future(coro.into_ref(py))
    //             })?;

    //             cb_fut.await?;
    //         }
    //         Ok(())
    //     })
    // }

    fn content(&self, py: Python<'_>) -> PyResult<Py<PyString>> {
        let cont: Py<PyString> = PyString::new(py, self.0.content().as_str()).into();
        Ok(cont)
    }

    fn send<'a>(&self, py: Python<'a>, skip: usize, text: String, tail: usize) -> PyResult<&'a PyAny>{
        let rc = self.0.clone();
        pyo3_asyncio::tokio::future_into_py(py, async move {
            Ok(())
        })
    } 
}

// #[pyclass]
// struct PyCursorEvent {
//     user: String,
//     buffer: Some(String),
//     start: (i32, i32),
//     end: (i32, i32)
// }

// impl From<CodempCursorEvent> for PyCursorEvent {
//     fn from(value: CodempCursorEvent) -> Self {
//         PyCursorEvent { 
//             user: value.user,
//             buffer: value.position.buffer,
//             start: (value.position.start.row, value.position.start.col),
//             end: (value.position.end.row, value.position.end.col) 
//         }
//     }
// }


// Python module
#[pymodule]
fn codemp_client(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(codemp_init, m)?)?;
    m.add_class::<PyClientHandle>()?;
    m.add_class::<PyCursorController>()?;
    m.add_class::<PyBufferController>()?;

    Ok(())
}