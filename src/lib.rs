use std::{sync::Arc, error::Error, borrow::BorrowMut};

use codemp::{
    client::CodempClient,
    controller::{cursor::{CursorSubscriber, CursorControllerHandle},
    buffer::{OperationControllerHandle, OperationControllerSubscriber}},
    proto::Position, factory::OperationFactory, tokio::sync::Mutex
};

use pyo3::{
    prelude::*,
    exceptions::PyConnectionError, 
    types::{PyBool, PyString}
};

#[pyfunction]
fn connect<'a>(py: Python<'a>, dest: String) -> PyResult<&'a PyAny> {
    // construct a python coroutine
    pyo3_asyncio::tokio::future_into_py(py, async move { 
        match CodempClient::new(dest.as_str()).await {
            Ok(c) => { 
                Python::with_gil(|py|{
                    let cc: PyClientHandle = c.into();
                    let handle = Py::new(py, cc)?;                    
                    Ok(handle)
                })
            },
            Err(e) => { Err(PyConnectionError::new_err(e.source().unwrap().to_string())) }
        }
    })
}

#[pyclass]
#[derive(Clone)]
struct PyClientHandle(Arc<Mutex<CodempClient>>);

impl From::<CodempClient> for PyClientHandle {
    fn from(value: CodempClient) -> Self {
        PyClientHandle(Arc::new(Mutex::new(value)))
    }
}

#[pymethods]
impl PyClientHandle {
    fn get_id<'a>(&self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();
        pyo3_asyncio::tokio::future_into_py(py, async move {
            let binding = rc.lock().await;

            Python::with_gil(|py| {
                let id: Py<PyString> = PyString::new(py, binding.id()).into();
                Ok(id)
            })
        })
    }

    fn create<'a>(&self, py: Python<'a>, path: String, content: Option<String>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            match rc.lock().await.create(path, content).await {
                Ok(accepted) => {
                    Python::with_gil(|py| {
                        let accepted: Py<PyBool> = PyBool::new(py, accepted).into();
                        Ok(accepted)
                    })
                },
                Err(e) => { Err(PyConnectionError::new_err(e.source().unwrap().to_string())) }
            }
            
        })
    }

    fn listen<'a>(&self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            match rc.lock().await.listen().await {
                Ok(controller) => {
                    Python::with_gil(|py| {
                       let cc: PyControllerHandle = controller.into();
                       let contr = Py::new(py, cc)?;
                       Ok(contr) 
                    })
                },
                Err(e) => {Err(PyConnectionError::new_err(e.source().unwrap().to_string()))}
            }
        })
    }

    fn attach<'a>(&self, py: Python<'a>, path: String) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();
        let uri = path.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            match rc.lock().await.attach(uri).await {
                Ok(factory) => {
                    Python::with_gil(|py| {
                       let ff: PyOperationsHandle = factory.into();
                       let fact = Py::new(py, ff)?;
                       Ok(fact) 
                    })
                },
                Err(e) => {Err(PyConnectionError::new_err(e.source().unwrap().to_string()))}
            }
        })
    }
}


impl From::<CursorControllerHandle> for PyControllerHandle {
    fn from(value: CursorControllerHandle) -> Self {
        PyControllerHandle(value)
    }
}

impl From::<OperationControllerHandle> for PyOperationsHandle {
    fn from(value: OperationControllerHandle) -> Self { 
        PyOperationsHandle(value)
    }
}

#[pyclass]
struct PyControllerHandle(CursorControllerHandle);

#[pymethods]
impl PyControllerHandle {
    fn callback<'a>(&'a self, py: Python<'a>, coro_py: Py<PyAny>, caller_id: Py<PyString>) -> PyResult<&'a PyAny> {
        let mut rc = self.0.clone();
        let cb = coro_py.clone();
        // We want to start polling the ControlHandle and call the callback every time
        // we have something.

        pyo3_asyncio::tokio::future_into_py(py, async move {
            while let Some(op) = rc.poll().await {
                let start = op.start.unwrap_or(Position { row: 0, col: 0});
                let end = op.end.unwrap_or(Position { row: 0, col: 0});

                let cb_fut = Python::with_gil(|py| -> PyResult<_> {
                    let args = (op.user, caller_id.clone(), op.buffer, (start.row, start.col), (end.row, end.col));
                    let coro = cb.call1(py, args)?;
                    pyo3_asyncio::tokio::into_future(coro.into_ref(py))
                })?;

                cb_fut.await?;
            }
            Ok(())
        })
    } // to call after polling cursor movements.

    fn send<'a>(&self, py: Python<'a>, path: String, start: (i32, i32), end: (i32, i32)) -> PyResult<&'a PyAny> {
        let rc = self.0.clone();

        pyo3_asyncio::tokio::future_into_py(py, async move {
            let startpos = Position { row: start.0, col: start.1 };
            let endpos = Position { row: end.0, col: end.1 };
            
            rc.send(path.as_str(), startpos, endpos).await;
            Ok(Python::with_gil(|py| py.None()))
        })

    } // when we change the cursor ourselves.
}

#[pyclass]
struct PyOperationsHandle(OperationControllerHandle);

#[pymethods]
impl PyOperationsHandle {
    fn callback<'a>(&'a self, py: Python<'a>, coro_py: Py<PyAny>, caller_id: Py<PyString>) -> PyResult<&'a PyAny> {
        let mut rc = self.0.clone();
        let cb = coro_py.clone();
         // We want to start polling the ControlHandle and call the callback every time
         // we have something.

        pyo3_asyncio::tokio::future_into_py(py, async move {
            while let Some(edit) = rc.poll().await {
                let start = edit.span.start;
                let end = edit.span.end;
                let text = edit.content;

                let cb_fut = Python::with_gil(|py| -> PyResult<_> {
                    let args = (caller_id.clone(), start, end, text);
                    let coro = cb.call1(py, args)?;
                    pyo3_asyncio::tokio::into_future(coro.into_ref(py))
                })?;

                cb_fut.await?;
            }
            Ok(())
        })
    } //to call after polling text changes

    fn content(&self, py: Python<'_>) -> PyResult<Py<PyString>> {
        let cont: Py<PyString> = PyString::new(py, self.0.content().as_str()).into();
        Ok(cont)
    }

    fn apply<'a>(&self, py: Python<'a>, skip: usize, text: String, tail: usize) -> PyResult<&'a PyAny>{
        let rc = self.0.clone();
        
        pyo3_asyncio::tokio::future_into_py(py, async move {

            match rc.delta(skip, text.as_str(), tail) {
                Some(op) => { rc.apply(op).await; Ok(()) },
                None => Err(PyConnectionError::new_err("delta failed"))
            }
            // if let Some(op) = rc.delta(skip, text.as_str(), tail) {
            //     rc.apply(op).await;
            //     Python::with_gil(|py| {
            //         let accepted: Py<PyBool> = PyBool::new(py, true).into();
            //         Ok(accepted)
            //     })
            // } else {
            //     Python::with_gil(|py| {
            //         let accepted: Py<PyBool> = PyBool::new(py, false).into();
            //         Ok(accepted)
            //     })
            // }
        })
    } //after making text mofications.
}


// Python module
#[pymodule]
fn codemp_client(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(connect, m)?)?;
    m.add_class::<PyClientHandle>()?;
    m.add_class::<PyControllerHandle>()?;
    m.add_class::<PyOperationsHandle>()?;

    Ok(())
}