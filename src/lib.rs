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
    Ok(Py::new(py, py_instance)?)
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
            let buffctrl: PyBufferController = rc.attach(path.as_str())
                .await
                .map_err(PyCodempError::from)?
                .into();

            Python::with_gil(|py| {
                Ok(Py::new(py, buffctrl)?)
            })
        })
    }

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
}

#[pyclass]
struct PyCursorController {
    handle: Arc<CodempCursorController>,
    cb_trigger: Option<tokio::sync::mpsc::UnboundedSender<()>>
}

impl From::<Arc<CodempCursorController>> for PyCursorController {
    fn from(value: Arc<CodempCursorController>) -> Self {
        PyCursorController {
            handle: value,
            cb_trigger: None
        }
    }
}

fn py_cursor_callback_wrapper(cb: PyObject) 
    -> Box<dyn FnMut(CodempCursorEvent) -> () + Send + Sync + 'static>
{
    let closure = move |data: CodempCursorEvent| {
        let args: PyCursorEvent = data.into();
        Python::with_gil(|py| { let _ = cb.call1(py, (args,)); });
    };
    Box::new(closure)
}

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
    fn drop_callback(&mut self) -> PyResult<()> {
        if let Some(channel) = &self.cb_trigger {
            channel.send(())
                .map_err(CodempError::from)
                .map_err(PyCodempError::from)?;

            self.cb_trigger = None;
        }
        Ok(())
    }

    fn callback<'a>(&'a mut self, py_cb: Py<PyAny>) -> PyResult<()> {
        if let Some(_channel) = &self.cb_trigger {
            Err(PyCodempError::from(CodempError::InvalidState { msg: "A callback is already running.".into() }).into())
        } else {
            let rt = pyo3_asyncio::tokio::get_runtime();

            // create a channel to stop the callback task running on the tokio runtime.
            // and save the sendent inside the python object, so that we can later call it.
            let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
            self.cb_trigger = Some(tx);

            self.handle.callback(rt, rx, py_cursor_callback_wrapper(py_cb));
            Ok(())
        }
    }

    fn send<'a>(&'a self, py: Python<'a>, path: String, start: (i32, i32), end: (i32, i32)) -> PyResult<&'a PyAny> {
        let rc = self.handle.clone();
        let pos = CodempCursorPosition {
            buffer: path,
            start: Some(start.into()),
            end: Some(end.into())
        };

        pyo3_asyncio::tokio::future_into_py(py, async move {
            rc.send(pos)
                .map_err(PyCodempError::from)?;
            Ok(())
        })

    }

    fn try_recv(&self, py: Python<'_>) -> PyResult<PyObject> {
        match self.handle.try_recv().map_err(PyCodempError::from)? {
            Some(cur_event) => {
                let evt = PyCursorEvent::from(cur_event);
                Ok(evt.into_py(py))
            },
            None => Ok(py.None())
        }
    }

    fn recv<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.handle.clone();

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
        let rc = self.handle.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            Ok(rc.poll().await.map_err(PyCodempError::from)?)
        })
    }
}

#[pyclass]
struct PyBufferController {
    handle: Arc<CodempBufferController>,
    cb_trigger: Option<tokio::sync::mpsc::UnboundedSender<()>>
}

impl From::<Arc<CodempBufferController>> for PyBufferController {
    fn from(value: Arc<CodempBufferController>) -> Self { 
        PyBufferController{
            handle: value,
            cb_trigger: None
        }
    }
}

fn py_buffer_callback_wrapper(cb: PyObject) 
    -> Box<dyn FnMut(CodempTextChange) -> () + Send + Sync + 'static>
{
    let closure = move |data: CodempTextChange| {
        let args: PyTextChange = data.into();
        Python::with_gil(|py| { let _ = cb.call1(py, (args,)); });
    };
    Box::new(closure)
}

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

    fn drop_callback(&mut self) -> PyResult<()> {
        if let Some(channel) = &self.cb_trigger {
            channel.send(())
                .map_err(CodempError::from)
                .map_err(PyCodempError::from)?;

            self.cb_trigger = None;
        }
        Ok(())
    }

    fn callback<'a>(&'a mut self, py_cb: Py<PyAny>) -> PyResult<()> {
        if let Some(_channel) = &self.cb_trigger {
            Err(PyCodempError::from(CodempError::InvalidState { msg: "A callback is already running.".into() }).into())
        } else {
            let rt = pyo3_asyncio::tokio::get_runtime();

            // could this be a oneshot channel?
            let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
            self.cb_trigger = Some(tx);

            self.handle.callback(rt, rx, py_buffer_callback_wrapper(py_cb));
            Ok(())
        }
    }


    fn replace(&self, txt: &str) -> PyResult<()> {
        if let Some(op) = self.handle.replace(txt) {
            self.handle.send(op).map_err(PyCodempError::from)?;
        }
        Ok(())
    }

    fn delta(&self, start: usize, txt: &str, end: usize) -> PyResult<()> {
        if let Some(op) = self.handle.delta(start, txt, end){
            self.handle.send(op).map_err(PyCodempError::from)?;
        }
        Ok(())
    }

    fn insert(&self, txt: &str, pos: u64) -> PyResult<()> {
        let op = self.handle.insert(txt, pos);
        self.handle.send(op).map_err(PyCodempError::from)?;
        Ok(())
    }

    fn delete(&self, pos: u64, count: u64) -> PyResult<()> {
        let op = self.handle.delete(pos, count);
        self.handle.send(op).map_err(PyCodempError::from)?;
        Ok(())
    }

    fn cancel(&self, pos: u64, count: u64) -> PyResult<()> {
        let op = self.handle.cancel(pos, count);
        self.handle.send(op).map_err(PyCodempError::from)?;
        Ok(())
    }

    fn content(&self, py: Python<'_>) -> PyResult<Py<PyString>> {
        let cont: Py<PyString> = PyString::new(py, self.handle.content().as_str()).into();
        Ok(cont)
    }

    // What to do with this send? does it make sense to implement it at all?
    // fn send<'a>(&self, py: Python<'a>, skip: usize, text: String, tail: usize) -> PyResult<&'a PyAny>{
    //     let rc = self.handle.clone();
    //     pyo3_asyncio::tokio::future_into_py(py, async move {
    //         Ok(())
    //     })
    // }

    fn try_recv(&self, py: Python<'_>) -> PyResult<PyObject> {
        match self.handle.try_recv().map_err(PyCodempError::from)? {
            Some(txt_change) => {
                let evt = PyTextChange::from(txt_change);
                Ok(evt.into_py(py))
            },
            None => Ok(py.None())
        }
    }

    fn recv<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.handle.clone();

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
        let rc = self.handle.clone();

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
    user: String,
    buffer: String,
    start: (i32, i32),
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
    start_incl: usize,
    end_excl: usize,
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


