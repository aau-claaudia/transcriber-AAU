import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { api as axios, apiFetch as fetch, appUrl } from './api.js';
import Settings from "./Settings.jsx";
import TranscriptionStatus from "./TranscriptionStatus.jsx";
import EditPage from "./EditPage.jsx";
import Notes from "./Notes.jsx";
import transcriberImage from "./logo-transcriber.png";
import HpcFiles from "./HpcFiles.jsx";
import ErrorOverlay from "./ErrorOverlay.jsx";

function App() {
    const getInitialArrayState = (keyname) => {
        const dataFromSession = sessionStorage.getItem(keyname);
        return dataFromSession ? JSON.parse(dataFromSession) : [];
    }
    const getInitialBooleanState = (keyname, state) => {
        const dataFromSession = sessionStorage.getItem(keyname);
        return dataFromSession ? JSON.parse(dataFromSession) : state;
    }
    const getInitialTranscriptionId = () => {
        const dataFromSession = sessionStorage.getItem("transcriptionId");
        return dataFromSession ? JSON.parse(dataFromSession) : null;
    }
    const getInitialTranscriptionStatus = () => {
        const dataFromSession = sessionStorage.getItem("statusText");
        return dataFromSession ? JSON.parse(dataFromSession) : null;
    }
    const getInitialString = (keyname, value) => {
        const dataFromSession = sessionStorage.getItem(keyname);
        return dataFromSession ? JSON.parse(dataFromSession) : value;
    }

    const TRANSCRIPTION_MODELS = {
        "whisper/base": 1.0,
        "whisper/small": 2.0,
        "whisper/medium": 5.0,
        "whisper/large-v3": 10.0,
        "whisper/large-v3-turbo": 6.0,
        "nvidia/parakeet-tdt-0.6b-v3": 4.0
    }

    /**
     * Determines the best default model based on available memory.
     * It returns the name of the largest model that fits the memory constraints.
     */
    const getDefaultModel = (availableMemory) => {
        const fittingModels = Object.entries(TRANSCRIPTION_MODELS)
            .filter(([_, memoryReq]) => memoryReq <= availableMemory)
            .sort(([, memA], [, memB]) => memB - memA); // Sort by memory descending

        // Return the name of the largest fitting model, or the most common if no models fit
        return fittingModels.length > 0 ? fittingModels[0][0] : 'large-v3';
    };

    const [files, setFiles] = useState([]);
    const [selectedHpcFiles, setSelectedHpcFiles] = useState([]);
    const [inputRoots, setInputRoots] = useState([]);
    const [resourceProfiles, setResourceProfiles] = useState({});
    const [resourceProfile, setResourceProfile] = useState('cpu-test');
    const [activeTask, setActiveTask] = useState(getInitialArrayState("activeTask"));
    const [rejected, setRejected] = useState([]);
    const [results, setResults] = useState(getInitialArrayState("results"));
    const [transcribing, setTranscribing] = useState(getInitialBooleanState("transcribing", false));
    const [buttonDisabled, setButtonDisabled] = useState(getInitialBooleanState("buttonDisabled", true));
    const [progress, setProgress] = useState(0)
    const [transcriptionId, setTranscriptionId] = useState(getInitialTranscriptionId);
    const transcriptionIdRef = useRef(transcriptionId);
    const [uploading, setUploading] = useState(getInitialBooleanState("uploading", false));
    const [statusText, setStatusText] = useState(getInitialTranscriptionStatus);
    const [transcriptionStatus, setTranscriptionStatus] = useState(null);
    const [showSettings, setShowSettings] = useState(false);
    const [transcribeAndShutdown, setTranscribeAndShutdown] = useState(false);
    const [serverStopped, setServerStopped] = useState(getInitialBooleanState("serverStopped", false));
    const [modelSize, setModelSize] = useState("large-v3");
    const [availableMemory, setAvailableMemory] = useState(16.0);
    const [language, setLanguage] = useState(getInitialString("language", "auto"))
    const [errorState, setErrorState] = useState(false);
    const [currentPage, setCurrentPage] = useState('dashboard');
    const [selectedTranscriptionKey, setSelectedTranscriptionKey] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const response = await fetch('/get-initialization-data/');
                if (!response.ok) {
                    throw new Error(`Server returned HTTP ${response.status}: ${response.statusText}`);
                }
                const initData = await response.json();
                setResults(initData.results ?? []);
                setSelectedHpcFiles([]);
                setInputRoots(initData.input_roots ?? []);
                setResourceProfiles(initData.resource_profiles ?? {});
                setResourceProfile(initData.active_transcription?.resource_profile
                    ?? Object.keys(initData.resource_profiles ?? {})[0] ?? 'cpu-test');
                const active = initData.active_transcription;
                setUploading(false);
                setServerStopped(false);
                setTranscriptionId(active?.task_id ?? null);
                setTranscribing(Boolean(active));
                setButtonDisabled(true);
                setActiveTask(active?.files ?? []);
                setStatusText(active?.status ?? '');
                setTranscriptionStatus(active ?? null);
                setCurrentPage(active ? 'upload' : 'dashboard');

                // get the size of the available memory
                const memory = initData.available_memory;
                console.debug('Available memory:', memory);
                if (memory && !isNaN(parseFloat(memory))) {
                    const memoryParsed = parseFloat(memory);
                    setAvailableMemory(memoryParsed);
                    setModelSize(initData.default_model ?? getDefaultModel(memoryParsed));
                } else {
                    console.debug("Unable to parse available memory as float value. Defaulting to 16.0 GB.")
                    setAvailableMemory(16.0);
                    setModelSize("large-v3");
                }
            } catch (err) {
                console.error('Error fetching initialization data:', err);
                setError(new Error("Unable to reach the transcription server."));
            }
        }
        // call the async function
        fetchData().catch(console.error);
    }, []); // Empty dependency array ensures this runs only once on component mount

    useEffect(() => {
        sessionStorage.setItem("language", JSON.stringify(language))
    }, [language]);
    useEffect(() => {
        sessionStorage.setItem("transcribeAndShutdown", JSON.stringify(transcribeAndShutdown))
    }, [transcribeAndShutdown]);
    useEffect(() => {
        sessionStorage.setItem("serverStopped", JSON.stringify(serverStopped))
    }, [serverStopped]);
    useEffect(() => {
        sessionStorage.setItem("results", JSON.stringify(results))
    }, [results]);
    useEffect(() => {
        sessionStorage.setItem("activeTask", JSON.stringify(activeTask))
    }, [activeTask]);
    useEffect(() => {
        sessionStorage.setItem("buttonDisabled", JSON.stringify(buttonDisabled))
    }, [buttonDisabled]);
    useEffect(() => {
        sessionStorage.setItem("transcribing", JSON.stringify(transcribing))
    }, [transcribing]);
    useEffect(() => {
        // file objects cannot be serialized properly with JSON.stringify. If we really want this serialization to the session we must pick metadata or store using library
        if (files.length === 0 && selectedHpcFiles.length === 0) {
            setButtonDisabled(true);
        } else if (!transcribing) {
            setButtonDisabled(false);
        }
    }, [files, selectedHpcFiles]);
    useEffect(() => {
        sessionStorage.setItem("transcriptionId", JSON.stringify(transcriptionId))
    }, [transcriptionId]);
    useEffect(() => {
        sessionStorage.setItem("statusText", JSON.stringify(statusText))
    }, [statusText]);
    useEffect(() => {
        sessionStorage.setItem("uploading", JSON.stringify(uploading))
    }, [uploading]);
    // Keep the ref updated with the latest transcriptionId
    useEffect(() => {
        transcriptionIdRef.current = transcriptionId;
    }, [transcriptionId]);

    // Function for showing or hiding the settings
    const showOrHideSettings = () => {
        setShowSettings(!showSettings);
    }

    useEffect(() => {
        if (!transcriptionId) return;
        const controller = new AbortController();
        let timer;
        const poll = async () => {
            try {
                const response = await fetch(`/poll-transcription-status/${transcriptionId}/`, {signal: controller.signal});
                if (!response.ok) throw new Error(`Unable to retrieve transcription: HTTP ${response.status}`);
                const data = await response.json();
                if (controller.signal.aborted) return;
                setStatusText(data.status);
                setTranscriptionStatus(data);
                if (['SUCCESS', 'FAILURE', 'CANCELLED'].includes(data.state)) {
                    setTranscriptionId(null);
                    setTranscribing(false);
                    setActiveTask([]);
                    if (data.state === 'SUCCESS') {
                        setResults(data.result ?? []);
                        setCurrentPage('dashboard');
                    }
                    if (data.state === 'FAILURE') setErrorState(true);
                    return;
                }
            } catch (error) {
                if (controller.signal.aborted) return;
                setStatusText('Status temporarily unavailable. Retrying...');
            }
            timer = setTimeout(poll, 5000);
        };
        poll();
        return () => {
            controller.abort();
            clearTimeout(timer);
        };
    }, [transcriptionId]);

    const inferDirNameFromFileUrl = (fileUrl) => {
        if (!fileUrl) return '';

        let pathname = '';
        try {
            pathname = new URL(fileUrl, window.location.href).pathname || '';
        } catch {
            pathname = String(fileUrl);
        }

        const marker = '/TRANSCRIPTIONS/';
        const markerIndex = pathname.indexOf(marker);
        if (markerIndex === -1) return '';

        let basePath = pathname.slice(0, markerIndex);
        if (basePath.startsWith(appUrl('/media/'))) {
            return basePath.slice(appUrl('/media/').length);
        }
        if (basePath.startsWith('/work/')) {
            return basePath.slice('/work/'.length);
        }
        return basePath.replace(/^\/+/, '');
    };

    // Group results by transcription directory (each folder is one run/input file)
    const groupedTranscriptions = results.reduce((acc, result) => {
        const dirName = result.dir_name || inferDirNameFromFileUrl(result.file_url);

        if (!dirName) {
            return acc;
        }

        if (!acc[dirName]) {
            acc[dirName] = {
                name: dirName,
                displayName: result.original_file_name,
                model: result.model,
                language: result.language,
                runPostFix: dirName.match(/_run\d+$/)?.[0].slice(1) || '',
                date: result.created_at || Date.now() / 1000,
                files: [],
                mergedFiles: [],
                logFiles: [],
                zipFile: null,
                inputFileUrl: result.input_file_url,
                editFileUrl: result.edit_file_url,
                userEdited: result.user_edited
            };
            //console.debug(acc[dirName]);
        }

        if (result.created_at && result.created_at > acc[dirName].date) {
            acc[dirName].date = result.created_at;
        }

        const fileName = result.file_name;
        if (fileName === 'transcribe.log' || fileName === 'transcriber_output.txt') {
            acc[dirName].logFiles.push(result);
        } else if (fileName === 'files.zip') {
            acc[dirName].zipFile = result;
        } else if (/_merged\.(?:csv|docx|dote\.json|srt|vtt)$/.test(fileName)) {
            acc[dirName].mergedFiles.push(result);
        } else {
            acc[dirName].files.push(result);
        }

        return acc;
    }, {});

    const setUserEditedStatus = (transcriptionKey) => {
        setResults(prevResults => {
            const needsUpdate = prevResults.some(item => {
                const dirName = item.dir_name || inferDirNameFromFileUrl(item.file_url);
                return dirName === transcriptionKey && !item.user_edited;
            });
            if (!needsUpdate) {
                // Return same array reference -> React bails out of re-rendering App
                //console.debug("Transcription already edited by user - not re-rendering dashboard.")
                return prevResults;
            }
            return prevResults.map(item => {
                const dirName = item.dir_name || inferDirNameFromFileUrl(item.file_url);
                if (dirName === transcriptionKey) {
                    return { ...item, user_edited: true };
                }
                return item;
            });
        });
    };

    // transform the rejected file data to group the files by the error type
    const groupedErrors = rejected.reduce((acc, file) => {
        file.errors.forEach(error => {
            if (!acc[error.message]) {
                acc[error.message] = [];
            }
            acc[error.message].push(file.file.name);
        });
        return acc;
    }, {});

    // Derived list of rows extracted from groupedTranscriptions for dashboard rendering
    const transcriptionRows = Object.values(groupedTranscriptions);

    // Upload files and start a transcription on the server
    const onTranscribe = async (e) => {
        e.preventDefault();
        setButtonDisabled(true); // Disable the button
        setUploading(true)
        setShowSettings(false); // hide settings
        setErrorState(false);
        setTranscriptionStatus(null);

        const formData = new FormData();
        // also create file meta data object to use for file size validation on uploads on the server side
        const fileMetaDataForValidation = [];
        files.forEach((file) => {
            formData.append('files', file);
            fileMetaDataForValidation.push({
                "filepath": "",
                "name": file.name,
                "size": file.size,
                "target_path_sym_link": "",
            })
        });
        formData.append('file_meta_data', JSON.stringify(fileMetaDataForValidation));
        formData.append('model', modelSize);
        formData.append('language', language);
        formData.append('resource_profile', resourceProfile);
        formData.append('transcribe_and_shutdown', transcribeAndShutdown);
        formData.append('existing_files', JSON.stringify(selectedHpcFiles.map(file => file.token)));

        try {
            const response = await axios.post('/upload/', formData, {
                onUploadProgress: (progressEvent) => {
                    const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                    setProgress(percentCompleted);
                },
                //headers: {
                //    'X-CSRFToken': csrfToken
                //}
            });
            console.debug('the transcription id is: ' + response.data.task_id)
            setTranscriptionId(response.data.task_id)
            setActiveTask(response.data.files ?? []);
            setUploading(false);
            setTranscribing(true);
            setStatusText(response.data.status);
            setTranscriptionStatus(response.data);
            resetFileArrays();
        } catch (error) {
            console.error('Error uploading file:', error);
            setUploading(false);
            setStatusText(error.response?.data?.error ?? "Unable to upload files.")
            setErrorState(true);
            setButtonDisabled(false);
        } finally {
            setProgress(0);
        }
    };

    const resetData = () => {
        setTranscriptionId(null);
        setTranscribing(false);
        setActiveTask([]);
        resetFileArrays()
    }

    const onStopTranscription = async (e) => {
        if (!transcriptionId) return;
        try {
            const response = await axios.post(`/stop_transcription_task/${transcriptionId}/`);
            setStatusText(response.data.status);
            setTranscriptionStatus(response.data);
            if (response.data.state === 'CANCELLED') resetData();
        } catch (error) {
            setError(new Error(error.response?.data?.error ?? 'Unable to cancel transcription.'));
        }
    };

    const resetFileArrays = () => {
        setFiles([]);
        setRejected([]);
        setSelectedHpcFiles([]);
    }

    const toggleHpcFile = file => {
        setErrorState(false);
        setSelectedHpcFiles(previous => previous.some(selected => selected.root === file.root && selected.path === file.path)
            ? previous.filter(selected => selected.root !== file.root || selected.path !== file.path)
            : [...previous, file]);
    };

    const onUpdateModel = (modelSize) => {
        setModelSize(modelSize)
    }

    const onUpdateLanguage = (language) => {
        setLanguage(language)
    }

    const onUpdateTranscribeAndShutdown = (flag) => {
        setTranscribeAndShutdown(flag);
    }

    const onDrop = useCallback((acceptedFiles, rejectedFiles) => {
        setErrorState(false);
        if (acceptedFiles?.length) {
            if (!transcribing) {
                setButtonDisabled(false);
            }
            setFiles(previousFiles => [
                ...previousFiles,
                ...acceptedFiles
            ])
        }
        setRejected([...rejectedFiles])
    }, [transcribing]);

    const removeFile = (name) => {
        setFiles(files => files.filter(file => file.name !== name))
    }

    const removeHpcFile = file => {
        setSelectedHpcFiles(previous => previous.filter(selected => selected.root !== file.root || selected.path !== file.path));
    };

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: {
            "audio/mpeg": [".mp3"],
            "audio/wav": [".wav"],
            "audio/x-ms-wma": [".wma"],
            "audio/x-m4a": [".m4a"],
            "video/mp4": [".mp4"],
            "video/mpeg": [".mpeg", ".mpg"],
            "video/x-matroska": [".mkv"]
        }
    });

    const setServerConnectionError = () => {
        setError(new Error("Unable to reach the transcription server."));
    }

    return (
        <div className="App">
            {/* Topbar */}
            <div className="topbar">
                <div className="logo-section" onClick={() => setCurrentPage('dashboard')} style={{ cursor: 'pointer' }}>
                    <img src={transcriberImage} alt="Transcriber" className="centered-image" />
                    <h1>Transcriber</h1>
                </div>
                <div className="topbar-actions">
                    <button
                        className="btn btn-primary"
                        onClick={() => setCurrentPage(currentPage === 'upload' ? 'dashboard' : 'upload')}
                    >
                        {currentPage === 'upload' ? '← Back to Dashboard' : transcribing ? 'Transcription status' : '+ New Transcription'}
                    </button>
                    <button
                        className="btn btn-secondary"
                        onClick={() => setShowSettings(true)}
                    >
                        ⚙️ Settings
                    </button>
                </div>
            </div>

            {/* Main Content Area */}
            {currentPage === 'dashboard' && (
                <div>
                    <h2>Transcribed Files</h2>
                    {transcriptionRows.length === 0 ? (
                        <div className="empty-state">
                            <div className="empty-state-icon">🎙️</div>
                            <h3>No Transcriptions Found</h3>
                            <p>Get started by uploading audio or video files for transcription.</p>
                            <button
                                className="btn btn-primary"
                                onClick={() => setCurrentPage('upload')}
                                style={{ marginTop: '1rem' }}
                            >
                                Create First Transcription
                            </button>
                        </div>
                    ) : (
                        <div className="dashboard-list">
                            {transcriptionRows.map((row, index) => {
                                const inputFileUrl = row.inputFileUrl || '';
                                const isVideo = inputFileUrl.endsWith('.mp4') || inputFileUrl.endsWith('.mkv') || inputFileUrl.endsWith('.mpeg') || inputFileUrl.endsWith('.mpg');
                                return (
                                    <button
                                        key={index}
                                        className="row-card"
                                        onClick={() => {
                                            setSelectedTranscriptionKey(row.name);
                                            setCurrentPage('edit');
                                        }}
                                    >
                                        <div className="row-info">
                                            <div className="row-icon-wrapper">
                                                {isVideo ? '🎥' : '🎵'}
                                            </div>
                                            <div className="row-details">
                                                <span className="row-title">{row.displayName || row.name} {row.runPostFix && row.runPostFix !== '' && `(${row.runPostFix})`} </span>
                                                <span className="row-date">
                                                    {row.model && <span className="badge-model">{row.model}</span>}
                                                    {row.language && `(${row.language}) • `}
                                                    Transcribed: {new Date(row.date * 1000).toLocaleString(undefined, {
                                                    year: 'numeric',
                                                    month: 'short',
                                                    day: 'numeric',
                                                    hour: '2-digit',
                                                    minute: '2-digit'
                                                })}
                                                    {row.userEdited && ` • Edited`}
                                                </span>
                                            </div>
                                        </div>
                                        <div className="row-actions">
                                            <span className="btn btn-secondary btn-sm" style={{ padding: '0.4rem 0.8rem' }}>
                                                ✏️ Edit & View
                                            </span>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            {currentPage === 'upload' && (
                <div className="card-panel" style={{ animation: 'fadeIn 0.4s ease-out' }}>
                    <h2>New Transcription</h2>
                    <p style={{ marginBottom: '1.5rem' }}>
                        Upload audio or video files from your computer.
                    </p>

                    {/* Selected files display */}
                    {(files.length > 0 || selectedHpcFiles.length > 0) && (
                        <div style={{ marginBottom: '1.5rem' }}>
                            <h3>Selected Files ({files.length + selectedHpcFiles.length})</h3>
                            <div className="file-list-group">
                                {files.map((file, index) => (
                                    <div className="file-item" key={'local-' + index}>
                                        <span className="file-name">📥 {file.name}</span>
                                        <div className="file-item-actions">
                                            <button className="remove-btn" type="button" onClick={() => removeFile(file.name)}>Remove</button>
                                        </div>
                                    </div>
                                ))}
                                {selectedHpcFiles.map((file, index) => (
                                    <div className="file-item" key={'hpc-' + index}>
                                        <span className="file-name">☁️ {file.name}</span>
                                        <div className="file-item-actions">
                                            <button className="remove-btn" type="button" onClick={() => removeHpcFile(file)}>Remove</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {rejected.length > 0 && (
                        <div style={{ marginBottom: '1.5rem' }}>
                            <h3 style={{ color: 'var(--accent-rose)' }}>Rejected Files</h3>
                            <div className="file-list-group" style={{ borderColor: 'var(--accent-rose)' }}>
                                {Object.keys(groupedErrors).map((errorMessage, index) => (
                                    <div key={index} style={{ padding: '0.5rem' }}>
                                        <p style={{ color: 'var(--accent-rose)', fontWeight: 'bold', fontSize: '0.85rem' }}>{errorMessage}</p>
                                        {groupedErrors[errorMessage].map((fileName, fileIndex) => (
                                            <div key={fileName + fileIndex} style={{ fontSize: '0.8rem', paddingLeft: '0.5rem', color: 'var(--text-secondary)' }}>
                                                • {fileName}
                                            </div>
                                        ))}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Action buttons */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', margin: '1.5rem 0' }}>
                        <button
                            type="button"
                            onClick={(e) => onTranscribe(e)}
                            className="btn btn-primary"
                            disabled={buttonDisabled}
                            style={{ minWidth: '160px' }}
                        >
                            {transcribing ? 'In Progress...' : '⚡ Start Transcription'}
                        </button>

                        <button
                            type="button"
                            onClick={(e) => onStopTranscription(e)}
                            className="btn btn-danger"
                            disabled={!transcribing}
                            style={{ minWidth: '160px' }}
                        >
                            🛑 Stop Transcription
                        </button>
                    </div>

                    {/* Drag and Drop Zone */}
                    {!transcribing && (
                        <div style={{ marginBottom: '2rem' }}>
                            <h3>Upload from Computer</h3>
                            <div {...getRootProps({ className: 'dropzone' })}>
                                <input {...getInputProps()} />
                                <div className="dropzone-icon">📥</div>
                                {isDragActive ? (
                                    <p>Drop the files here ...</p>
                                ) : (
                                    <p>Drag & drop audio/video files here, or click to browse</p>
                                )}
                            </div>
                        </div>
                    )}

                    {!transcribing && inputRoots.length > 0 && (
                        <HpcFiles roots={inputRoots} selectedFiles={selectedHpcFiles}
                            onToggle={toggleHpcFile} disabled={uploading} />
                    )}

                    {/* Status panel */}
                    {(uploading || transcribing || errorState || transcriptionStatus?.state === 'CANCELLED') && (
                        <div className="status-panel">
                            <h3>Status</h3>
                            {uploading && <p>Uploading files: {progress}%</p>}
                            {errorState && !transcriptionStatus && <p style={{ color: 'var(--accent-rose)' }}>{statusText}</p>}
                            {(transcribing || ['FAILURE', 'CANCELLED'].includes(transcriptionStatus?.state)) && (
                                <TranscriptionStatus
                                    statusText={statusText}
                                    activeTask={transcriptionStatus?.files ?? activeTask}
                                    status={transcriptionStatus ?? {}}
                                />
                            )}
                        </div>
                    )}
                </div>
            )}

            {currentPage === 'edit' && selectedTranscriptionKey && (
                <EditPage
                    transcriptionKey={selectedTranscriptionKey}
                    transcriptionData={groupedTranscriptions[selectedTranscriptionKey]}
                    onBack={() => setCurrentPage('dashboard')}
                    onOpenNotes={() => setCurrentPage('notes')}
                    onServerError={setServerConnectionError}
                />
            )}

            {currentPage === 'notes' && selectedTranscriptionKey && (
                <Notes
                    transcriptionKey={selectedTranscriptionKey}
                    transcriptionData={groupedTranscriptions[selectedTranscriptionKey]}
                    onBackToDashboard={() => setCurrentPage('dashboard')}
                    onBackToEdit={() => setCurrentPage('edit')}
                    onUpdateUserEditedStatus={setUserEditedStatus}
                    onServerError={setServerConnectionError}
                />
            )}

            {/* Settings Modal */}
            {showSettings && (
                <div className="modal-overlay" onClick={() => setShowSettings(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()}>
                        <button className="modal-close-btn" onClick={() => setShowSettings(false)}>×</button>
                        <Settings
                            onUpdateModel={onUpdateModel}
                            currentModelSize={modelSize}
                            availableMemory={availableMemory}
                            resourceProfiles={resourceProfiles}
                            resourceProfile={resourceProfile}
                            onUpdateResourceProfile={profile => {
                                setResourceProfile(profile);
                                setAvailableMemory(resourceProfiles[profile]?.memory_gb ?? 16);
                            }}
                            transcriptionModels={TRANSCRIPTION_MODELS}
                            onUpdateLanguage={onUpdateLanguage}
                            currentLanguage={language}
                            onUpdateTranscribeAndShutdown={onUpdateTranscribeAndShutdown}
                            currentTranscribeAndShutdown={transcribeAndShutdown}
                        />
                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
                            <button className="btn btn-primary" onClick={() => setShowSettings(false)}>Close</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Global Error Overlay */}
            <ErrorOverlay
                error={error}
                onClose={() => setError(null)}
                onRefresh={() => window.location.reload()}
            />
        </div>
    );
}

export default App;