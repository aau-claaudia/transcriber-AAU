import React, { useState, useEffect, useRef, useMemo } from 'react';
import { apiFetch as fetch, appUrl } from './api.js';

// Utility helper to convert HH:MM:SS.mmm to seconds
function timestampToSeconds(timestamp) {
    if (!timestamp) return 0;
    const parts = timestamp.split(':');
    if (parts.length !== 3) return 0;
    const hours = parseInt(parts[0], 10);
    const minutes = parseInt(parts[1], 10);
    const secondsWithMs = parseFloat(parts[2]);
    return hours * 3600 + minutes * 60 + secondsWithMs;
}

// Single-control UI for one segment, driven by shared player state
const SegmentAudioPlayer = ({
                                audioUrl,
                                segmentId,
                                activeSegmentId,
                                currentTimeBySegment,
                                onToggleSegment,
                                onSeekSegment,
                                startTimeStr,
                                endTimeStr
                            }) => {
    const startSecs = timestampToSeconds(startTimeStr);
    const endSecs = timestampToSeconds(endTimeStr);
    const duration = Math.max(0.1, endSecs - startSecs);

    const isPlaying = activeSegmentId === segmentId;
    const currentTime = currentTimeBySegment[segmentId] ?? 0;
    const progressPercent = Math.max(0, Math.min(100, (currentTime / duration) * 100));

    const handleProgressClick = (e) => {
        if (!audioUrl) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const width = rect.width || 1;
        const clickRatio = Math.max(0, Math.min(1, clickX / width));
        const relativeTime = clickRatio * duration;
        onSeekSegment(segmentId, relativeTime);
    };

    if (!audioUrl) {
        return (
            <div className="segment-audio-player" style={{ opacity: 0.5 }} title="Audio source file not available">
                <button className="play-segment-btn" disabled>▶️</button>
                <div className="segment-progress-container" style={{ cursor: 'not-allowed' }}>
                    <div className="segment-progress-bar" style={{ width: '0%' }}></div>
                </div>
                <span className="segment-time-label">0.0s / {duration.toFixed(1)}s</span>
            </div>
        );
    }

    return (
        <div className="segment-audio-player">
            <button
                className="play-segment-btn"
                onClick={() => onToggleSegment(segmentId)}
                title={isPlaying ? 'Pause Segment' : 'Play Segment'}
            >
                {isPlaying ? '⏸️' : '▶️'}
            </button>
            <div className="segment-progress-container" onClick={handleProgressClick}>
                <div className="segment-progress-bar" style={{ width: `${progressPercent}%` }}></div>
            </div>
            <span className="segment-time-label">
                {currentTime.toFixed(1)}s / {duration.toFixed(1)}s
            </span>
        </div>
    );
};

// Segment Card containing speaker, duration, audio controls, text and selection-based note adding form
const SegmentCard = ({
                         segment,
                         segmentId,
                         audioUrl,
                         activeSegmentId,
                         currentTimeBySegment,
                         onToggleSegment,
                         onSeekSegment,
                         onAddNote,
                         editMode,
                         onUpdateSegmentText,
                         onUpdateSpeaker
                     }) => {
    const [selectionState, setSelectionState] = useState({ text: '', isOpen: false });
    const [correctiveText, setCorrectiveText] = useState('');
    const [isEditingSpeaker, setIsEditingSpeaker] = useState(false);
    const [newSpeakerName, setNewSpeakerName] = useState(segment.speakerDesignation);

    useEffect(() => {
        setNewSpeakerName(segment.speakerDesignation);
    }, [segment.speakerDesignation]);

    const handleSegmentTextClick = () => {
        setSelectionState({ text: segment.text, isOpen: true });
        setCorrectiveText(segment.text);
    };

    const handleSaveNote = () => {
        if (!correctiveText.trim()) return;

        const formattedNote = `${segment.startTime} - ${segment.endTime}: ${selectionState.text} -> ${correctiveText}`;
        onAddNote(formattedNote);

        setCorrectiveText('');
        setSelectionState({ text: '', isOpen: false });
    };

    const handleApplyEdit = () => {
        if (!correctiveText.trim()) return;

        onUpdateSegmentText(segmentId, correctiveText);

        setCorrectiveText('');
        setSelectionState({ text: '', isOpen: false });
    };

    const handleCancel = () => {
        setCorrectiveText('');
        setSelectionState({ text: '', isOpen: false });
    };

    const handleCorrectiveInputKeyDown = (e, editMode) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            handleCancel();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (editMode) {
                handleApplyEdit();
            } else {
                handleSaveNote();
            }
        }
    };

    return (
        <div className="segment-card">
            <div className="segment-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.75rem' }}>
                {isEditingSpeaker ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', background: 'var(--selection-form-bg)', border: '1px solid var(--selection-form-border)', padding: '0.75rem', borderRadius: 'var(--radius-md)', width: '100%' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>Rename Speaker:</span>
                            <input
                                type="text"
                                className="note-input-field"
                                value={newSpeakerName}
                                onChange={(e) => setNewSpeakerName(e.target.value)}
                                style={{ flex: 1, padding: '0.3rem 0.6rem', fontSize: '0.85rem', background: 'var(--note-input-bg)', border: '1px solid var(--note-input-border)', borderRadius: 'var(--radius-sm)', color: 'var(--note-input-text)' }}
                                autoFocus
                            />
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => {
                                    setIsEditingSpeaker(false);
                                    setNewSpeakerName(segment.speakerDesignation);
                                }}
                                style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-secondary"
                                onClick={() => {
                                    onUpdateSpeaker(segment.speakerDesignation, newSpeakerName, false, segmentId);
                                    setIsEditingSpeaker(false);
                                }}
                                style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}
                            >
                                This Segment Only
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={() => {
                                    onUpdateSpeaker(segment.speakerDesignation, newSpeakerName, true, segmentId);
                                    setIsEditingSpeaker(false);
                                }}
                                style={{ padding: '0.25rem 0.6rem', fontSize: '0.75rem' }}
                            >
                                All Segments
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        <span
                            className="speaker-badge"
                            style={{ cursor: editMode ? 'pointer' : 'default' }}
                            onClick={() => { if (editMode) setIsEditingSpeaker(true); }}
                            title={editMode ? "Click to rename speaker" : ""}
                        >
                            👤 {segment.speakerDesignation} {editMode && <span style={{ fontSize: '0.75rem', opacity: 0.8, marginLeft: '0.25rem' }}>✏️</span>}
                        </span>
                        <span className="time-badge">⏱️ {segment.startTime} - {segment.endTime}</span>
                    </>
                )}
            </div>

            <SegmentAudioPlayer
                audioUrl={audioUrl}
                segmentId={segmentId}
                activeSegmentId={activeSegmentId}
                currentTimeBySegment={currentTimeBySegment}
                onToggleSegment={onToggleSegment}
                onSeekSegment={onSeekSegment}
                startTimeStr={segment.startTime}
                endTimeStr={segment.endTime}
            />

            <div
                className="segment-text"
                onClick={handleSegmentTextClick}
                title="Click text to edit or annotate this segment"
            >
                {segment.text}
            </div>

            {selectionState.isOpen && (
                <div className="segment-selection-form">
                    <div className="selected-text-preview">
                        Current text: "<strong>{selectionState.text}</strong>"
                    </div>
                    <input
                        type="text"
                        className="note-input-field"
                        placeholder={editMode ? "Enter replacement text..." : "Enter corrective note / comments..."}
                        value={correctiveText}
                        onChange={(e) => setCorrectiveText(e.target.value)}
                        onKeyDown={(e) => handleCorrectiveInputKeyDown(e, editMode)}
                        autoFocus
                    />
                    <div className="form-actions">
                        <button className="btn btn-secondary" onClick={handleCancel} style={{ padding: '0.3rem 0.75rem', fontSize: '0.8rem' }}>
                            Cancel
                        </button>
                        <button
                            className="btn btn-primary"
                            onClick={editMode ? handleApplyEdit : handleSaveNote}
                            style={{ padding: '0.3rem 0.75rem', fontSize: '0.8rem' }}
                        >
                            {editMode ? 'Apply Edit' : 'Save Note'}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

const Notes = ({ transcriptionKey, transcriptionData, onBackToDashboard, onBackToEdit, onUpdateUserEditedStatus, onServerError }) => {
    const [notes, setNotes] = useState([]);
    const [segments, setSegments] = useState([]);
    const [loadingSegments, setLoadingSegments] = useState(true);
    const [errorSegments, setErrorSegments] = useState(null);
    const [editMode, setEditMode] = useState(false);

    // Segment-panel save status: 'idle' | 'saving' | 'error'
    const [saveStatus, setSaveStatus] = useState('idle');
    const [saveError, setSaveError] = useState(null);

    // Notes-panel save status: 'idle' | 'saving' | 'error'
    const [noteSaveStatus, setNoteSaveStatus] = useState('idle');
    const [noteSaveError, setNoteSaveError] = useState(null);

    // Export Modal State
    const [showExportModal, setShowExportModal] = useState(false);
    const [exportTarget, setExportTarget] = useState('edited_output'); // 'edited_output' | 'notes'
    const [exportFormat, setExportFormat] = useState('json'); // 'json' | 'txt' | 'docx'
    const [mergedFormat, setMergedFormat] = useState('off'); // 'off' | 'on'

    const handleDownloadExport = () => {
        const dirName = transcriptionData?.name;
        if (!dirName) return;

        const downloadUrl = appUrl(`/export-file/?dir_name=${encodeURIComponent(dirName)}&target=${exportTarget}&format=${exportFormat}&merged=${mergedFormat}`);

        const link = document.createElement('a');
        link.href = downloadUrl;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setShowExportModal(false);
    };

    // Returns a Promise that resolves on success and rejects on any failure.
    const sendEditUpdateToBackend = (editPayload) => {
        console.debug("Sending edit update to backend:", editPayload);
        const dirName = transcriptionData?.name;
        if (!dirName) {
            return Promise.reject(new Error('No transcription directory name available.'));
        }

        setSaveStatus('saving');
        setSaveError(null);

        return fetch('/edit-transcription-segment/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                dir_name: dirName,
                payload: editPayload
            })
        })
            .then(res => {
                if (!res.ok) {
                    throw new Error(`Server returned ${res.status} ${res.statusText}`);
                }
                return res.json();
            })
            .then(data => {
                console.debug("Edit successfully saved on backend:", data);
                setSaveStatus('idle');
                onUpdateUserEditedStatus(dirName);
            });
    };

    const handleUpdateSegmentText = (segmentId, newText) => {
        // Snapshot state before the optimistic update so we can roll back on error
        const previousSegments = segments;

        setSegments(prev => prev.map((seg, idx) => {
            if (idx === segmentId) {
                return { ...seg, text: newText };
            }
            return seg;
        }));

        sendEditUpdateToBackend({
            type: 'text_edit',
            segmentId,
            newText
        }).catch(err => {
            console.error("Failed to save text edit on backend:", err);
            // Roll back optimistic update so the UI reflects the real state
            setSegments(previousSegments);
            setSaveStatus('error');
            setSaveError('Could not save the text edit. Please check your connection and try again.');
        });
    };

    const handleUpdateSpeaker = (oldName, newName, updateAll, segmentId) => {
        // Snapshot state before the optimistic update so we can roll back on error
        const previousSegments = segments;

        setSegments(prev => prev.map((seg, idx) => {
            if (updateAll) {
                if (seg.speakerDesignation === oldName) {
                    return { ...seg, speakerDesignation: newName };
                }
            } else {
                if (idx === segmentId) {
                    return { ...seg, speakerDesignation: newName };
                }
            }
            return seg;
        }));

        sendEditUpdateToBackend({
            type: 'speaker_edit',
            oldName,
            newName,
            updateAll,
            segmentId
        }).catch(err => {
            console.error("Failed to save speaker edit on backend:", err);
            // Roll back optimistic update so the UI reflects the real state
            setSegments(previousSegments);
            setSaveStatus('error');
            setSaveError('Could not save the speaker rename. Please check your connection and try again.');
        });
    };

    // Audio URL state — may be updated after server-side conversion
    const [audioUrl, setAudioUrl] = useState(transcriptionData?.inputFileUrl ?? null);
    const [audioConverting, setAudioConverting] = useState(false);

    // Shared audio state
    const audioRef = useRef(null);
    const [activeSegmentId, setActiveSegmentId] = useState(null);
    const [currentTimeBySegment, setCurrentTimeBySegment] = useState({});

    // Segment timing cache for shared player logic
    const segmentBounds = useMemo(() => {
        return segments.map((s) => ({
            start: timestampToSeconds(s.startTime),
            end: timestampToSeconds(s.endTime)
        }));
    }, [segments]);

    // Get .dote.json file from transcriptionData files
    const doteFileUrl = transcriptionData?.editFileUrl ??
        transcriptionData?.files?.find((f) => f.file_name.endsWith(".dote.json"))?.file_url;

    // method for creating relative links from the file URLs
    const toRelativeFetchUrl = (fileUrl) => {
        if (!fileUrl) return fileUrl;
        try {
            const parsedUrl = new URL(fileUrl, window.location.href, true);

            const pathname = parsedUrl.pathname || '';
            const search = parsedUrl.search || '';

            return `${pathname}${search}`;
        } catch (err) {
            console.warn('Could not parse file URL, using original value:', fileUrl, err);
            return fileUrl;
        }
    }

    // On mount: if the audio source isn't already .mp3 or .wav, request server conversion
    useEffect(() => {
        const rawUrl = transcriptionData?.inputFileUrl;
        const dirName = transcriptionData?.name;
        if (!rawUrl) {
            setAudioUrl(null);
            return;
        }

        // Extract the path extension
        let ext = '';
        try {
            ext = new URL(rawUrl).pathname.split('.').pop().toLowerCase();
        } catch {
            ext = rawUrl.split('.').pop().toLowerCase();
        }

        const nativeFormats = new Set(['mp3', 'wav']);
        if (nativeFormats.has(ext)) {
            // Already in a browser-native format — use as-is
            setAudioUrl(rawUrl);
            return;
        }

        // Trigger conversion of video/audio file
        if (!dirName) {
            // No dir context to convert — fall back to original URL
            setAudioUrl(rawUrl);
            return;
        }

        setAudioConverting(true);
        fetch('/convert-audio/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir_name: dirName, input_file_url: rawUrl }),
        })
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(data => {
                setAudioUrl(data.input_file_url || rawUrl);
            })
            .catch(err => {
                console.error('Audio conversion request failed:', err);
                setAudioUrl(rawUrl); // graceful fallback
            })
            .finally(() => {
                setAudioConverting(false);
            });
    }, [transcriptionData?.inputFileUrl, transcriptionData?.name]);

    // Load notes from server on mount
    useEffect(() => {
        const dirName = transcriptionData?.name;
        if (!dirName) {
            setNotes([]);
            return;
        }

        fetch(`/get-notes/?dir_name=${encodeURIComponent(dirName)}`)
            .then(res => {
                if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
                return res.json();
            })
            .then(data => {
                // Already sorted ascending by the server
                setNotes(data.notes ?? []);
            })
            .catch(err => {
                console.error('Failed to load notes from server:', err);
                setNotes([]);
                onServerError();
            });
    }, [transcriptionData?.name]);

    // Fetch transcription segments from dote.json
    useEffect(() => {
        if (!doteFileUrl) {
            setSegments([]);
            setLoadingSegments(false);
            setErrorSegments('No .dote.json file found for this transcription run.');
            return;
        }

        setLoadingSegments(true);
        setErrorSegments(null);

        fetch(toRelativeFetchUrl(doteFileUrl))
            .then(res => {
                if (!res.ok) {
                    throw new Error(`Failed to load dote.json: ${res.statusText}`);
                }
                return res.json();
            })
            .then(data => {
                if (data && Array.isArray(data.lines)) {
                    setSegments(data.lines);
                } else {
                    setSegments([]);
                    setErrorSegments("Dote file format invalid (missing 'lines' array).");
                }
                setLoadingSegments(false);
            })
            .catch(err => {
                console.error('Error loading dote file:', err);
                setErrorSegments('Could not load transcription segments from the server.');
                setLoadingSegments(false);
            });
    }, [doteFileUrl]);

    // Refs so that event listeners always see current values without being recreated
    const activeSegmentIdRef = useRef(null);
    const segmentBoundsRef = useRef([]);

    // Keep refs in sync with state/memo
    useEffect(() => { activeSegmentIdRef.current = activeSegmentId; }, [activeSegmentId]);
    useEffect(() => { segmentBoundsRef.current = segmentBounds; }, [segmentBounds]);

    // Create one shared Audio element — only recreated when the source URL changes
    useEffect(() => {
        if (!audioUrl) {
            audioRef.current = null;
            setActiveSegmentId(null);
            setCurrentTimeBySegment({});
            return;
        }

        const audio = new Audio(audioUrl);
        audio.preload = 'metadata';
        audio.autoplay = false;
        audioRef.current = audio;

        const onTimeUpdate = () => {
            const segId = activeSegmentIdRef.current;
            if (segId == null) return;
            const bounds = segmentBoundsRef.current[segId];
            if (!bounds) return;

            const relative = Math.max(0, audio.currentTime - bounds.start);

            if (audio.currentTime >= bounds.end) {
                audio.pause();
                audio.currentTime = bounds.start;
                setCurrentTimeBySegment(prev => ({ ...prev, [segId]: 0 }));
                setActiveSegmentId(null);
                activeSegmentIdRef.current = null;
                return;
            }

            setCurrentTimeBySegment(prev => ({ ...prev, [segId]: relative }));
        };

        const onEnded = () => {
            const segId = activeSegmentIdRef.current;
            if (segId != null) {
                setCurrentTimeBySegment(prev => ({ ...prev, [segId]: 0 }));
            }
            setActiveSegmentId(null);
            activeSegmentIdRef.current = null;
        };

        audio.addEventListener('timeupdate', onTimeUpdate);
        audio.addEventListener('ended', onEnded);

        return () => {
            audio.pause();
            audio.removeEventListener('timeupdate', onTimeUpdate);
            audio.removeEventListener('ended', onEnded);
        };
    }, [audioUrl]);

    // Toggle play/pause for a segment using shared audio
    const handleToggleSegment = (segmentId) => {
        const audio = audioRef.current;
        if (!audio) return;

        const bounds = segmentBounds[segmentId];
        if (!bounds) return;

        if (activeSegmentId === segmentId) {
            audio.pause();
            setActiveSegmentId(null);
            return;
        }

        setActiveSegmentId(segmentId);

        // Ensure playhead is inside target segment window
        if (audio.currentTime < bounds.start || audio.currentTime >= bounds.end) {
            audio.currentTime = bounds.start;
            setCurrentTimeBySegment(prev => ({ ...prev, [segmentId]: 0 }));
        }

        audio.play().catch(err => {
            // AbortError is expected when a pending play gets superseded by pause/seek
            if (err?.name !== 'AbortError') {
                console.error('Audio playback error:', err);
            }
        });
    };

    // Seek within one segment (relative seconds)
    const handleSeekSegment = (segmentId, relativeTime) => {
        const audio = audioRef.current;
        if (!audio) return;

        const bounds = segmentBounds[segmentId];
        if (!bounds) return;

        const duration = Math.max(0.1, bounds.end - bounds.start);
        const clampedRelative = Math.max(0, Math.min(duration, relativeTime));
        const absoluteTarget = bounds.start + clampedRelative;

        audio.currentTime = absoluteTarget;
        setCurrentTimeBySegment(prev => ({ ...prev, [segmentId]: clampedRelative }));

        if (activeSegmentId !== segmentId) {
            setActiveSegmentId(segmentId);
            audio.play().catch(err => {
                if (err?.name !== 'AbortError') {
                    console.error('Audio playback error:', err);
                }
            });
        }
    };

    const handleAddNote = (noteText) => {
        const dirName = transcriptionData?.name;
        if (!dirName) return;

        setNoteSaveStatus('saving');
        setNoteSaveError(null);

        fetch('/save-note/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir_name: dirName, note: noteText }),
        })
            .then(res => {
                if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
                return res.json();
            })
            .then(data => {
                // Server assigned the id — append at end (list is earliest-first)
                setNotes(prev => [...prev, data.note]);
                setNoteSaveStatus('idle');
                onUpdateUserEditedStatus(dirName);
            })
            .catch(err => {
                console.error('Failed to save note on server:', err);
                setNoteSaveStatus('error');
                setNoteSaveError('Could not save the note. Please check your connection and try again.');
            });
    };

    const handleDeleteNote = (noteId) => {
        const dirName = transcriptionData?.name;
        if (!dirName) return;

        // Snapshot for potential rollback
        const previousNotes = notes;

        // Optimistic removal
        setNotes(prev => prev.filter(n => n.id !== noteId));
        setNoteSaveStatus('saving');
        setNoteSaveError(null);

        fetch('/delete-note/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir_name: dirName, note_id: noteId }),
        })
            .then(res => {
                if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
                return res.json();
            })
            .then(() => {
                setNoteSaveStatus('idle');
            })
            .catch(err => {
                console.error('Failed to delete note on server:', err);
                // Roll back optimistic removal
                setNotes(previousNotes);
                setNoteSaveStatus('error');
                setNoteSaveError('Could not delete the note. Please check your connection and try again.');
            });
    };

    return (
        <div className="notes-page" style={{ animation: 'fadeIn 0.4s ease-out' }}>
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                    <button className="btn btn-secondary" onClick={onBackToEdit}>
                        ← Back to Results Page
                    </button>
                    <button className="btn btn-secondary" onClick={() => setShowExportModal(true)}>
                        📥 Export
                    </button>
                </div>
                <h2 style={{ margin: 0, fontSize: '1.5rem' }}>{editMode ? 'Editing' : 'Annotating'}: {transcriptionKey}</h2>
            </div>

            <div className="notes-page-layout">
                <div className="card-panel" style={{ position: 'relative' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
                        <h3 style={{ margin: 0 }}>
                            🎙️ Transcription Segments
                        </h3>
                        <div className="toggle-container" style={{ margin: 0, gap: '0.5rem' }}>
                            <span className="toggle-label" style={{ fontSize: '0.85rem' }}>Edit Mode</span>
                            <label className="toggle-switch">
                                <input
                                    type="checkbox"
                                    checked={editMode}
                                    onChange={(e) => setEditMode(e.target.checked)}
                                />
                                <span className="slider"></span>
                            </label>
                        </div>
                    </div>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                        {
                            editMode ? "To edit the transcription output, click any segment text to open a prefilled input. Use the audio controls next to each segment to verify speaker pronunciation."
                                : "To add a corrective note, click any segment text to open a prefilled input. Use the audio controls next to each segment to verify speaker pronunciation."
                        }
                    </p>

                    {/* Audio conversion loading overlay */}
                    {audioConverting && (
                        <div style={{
                            position: 'absolute',
                            inset: 0,
                            borderRadius: 'var(--radius-lg, 12px)',
                            background: 'var(--overlay-bg)',
                            backdropFilter: 'blur(6px)',
                            WebkitBackdropFilter: 'blur(6px)',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '1rem',
                            zIndex: 10,
                        }}>
                            <div style={{
                                width: '48px',
                                height: '48px',
                                borderRadius: '50%',
                                border: '3px solid var(--spinner-border)',
                                borderTopColor: 'var(--accent-violet, #8b5cf6)',
                                animation: 'spin 0.9s linear infinite',
                            }} />
                            <div style={{ textAlign: 'center' }}>
                                <p style={{ margin: 0, fontWeight: 600, fontSize: '1rem', color: 'var(--text-primary, #f1f5f9)' }}>
                                    🎵 Converting audio to MP3…
                                </p>
                                <p style={{ margin: '0.35rem 0 0', fontSize: '0.8rem', color: 'var(--text-muted, #64748b)' }}>
                                    This may take a moment for large files
                                </p>
                            </div>
                            {/* Shimmer bar */}
                            <div style={{
                                width: '180px',
                                height: '4px',
                                borderRadius: '2px',
                                background: 'var(--shimmer-bg)',
                                overflow: 'hidden',
                            }}>
                                <div style={{
                                    height: '100%',
                                    width: '40%',
                                    borderRadius: '2px',
                                    background: 'linear-gradient(90deg, transparent, var(--accent-violet, #8b5cf6), transparent)',
                                    animation: 'shimmer 1.4s ease-in-out infinite',
                                }} />
                            </div>
                        </div>
                    )}

                    {/* Edit save in-progress overlay — shown while waiting for backend to confirm */}
                    {saveStatus === 'saving' && (
                        <div style={{
                            position: 'absolute',
                            inset: 0,
                            borderRadius: 'var(--radius-lg, 12px)',
                            background: 'var(--overlay-bg)',
                            backdropFilter: 'blur(4px)',
                            WebkitBackdropFilter: 'blur(4px)',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.75rem',
                            zIndex: 10,
                            pointerEvents: 'none',
                        }}>
                            <p style={{ margin: 0, fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                                💾 Saving edit…
                            </p>
                            {/* Shimmer bar */}
                            <div style={{
                                width: '160px',
                                height: '4px',
                                borderRadius: '2px',
                                background: 'var(--shimmer-bg)',
                                overflow: 'hidden',
                            }}>
                                <div style={{
                                    height: '100%',
                                    width: '40%',
                                    borderRadius: '2px',
                                    background: 'linear-gradient(90deg, transparent, var(--accent-violet), transparent)',
                                    animation: 'shimmer 1.4s ease-in-out infinite',
                                }} />
                            </div>
                        </div>
                    )}

                    {/* Edit save error banner — shown when backend rejected or did not respond */}
                    {saveStatus === 'error' && saveError && (
                        <div style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.75rem',
                            padding: '0.75rem 1rem',
                            marginBottom: '1rem',
                            background: 'var(--error-bg)',
                            border: '1px solid var(--accent-rose)',
                            borderRadius: 'var(--radius-md)',
                            color: 'var(--error-text)',
                            fontSize: '0.875rem',
                        }}>
                            <span style={{ fontSize: '1.1rem', flexShrink: 0 }}>⚠️</span>
                            <div style={{ flex: 1 }}>
                                <strong>Save failed.</strong> {saveError}
                            </div>
                            <button
                                onClick={() => { setSaveStatus('idle'); setSaveError(null); }}
                                title="Dismiss"
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: 'var(--error-text)',
                                    fontSize: '1rem',
                                    lineHeight: 1,
                                    padding: '0',
                                    flexShrink: 0,
                                }}
                            >
                                ✕
                            </button>
                        </div>
                    )}

                    {loadingSegments && (
                        <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                            Loading transcription segments...
                        </div>
                    )}

                    {errorSegments && (
                        <div style={{ padding: '1rem', background: 'var(--error-bg)', border: '1px solid var(--accent-rose)', borderRadius: 'var(--radius-md)', color: 'var(--error-text)', fontSize: '0.9rem' }}>
                            {errorSegments}
                        </div>
                    )}

                    {!loadingSegments && !errorSegments && segments.length === 0 && (
                        <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-muted)' }}>
                            No transcription segments found in the dote output file.
                        </div>
                    )}

                    {!loadingSegments && !errorSegments && segments.length > 0 && (
                        <div className="segment-list">
                            {segments.map((segment, idx) => (
                                <SegmentCard
                                    key={segment.id}
                                    segmentId={segment.id}
                                    segment={segment}
                                    audioUrl={audioUrl}
                                    activeSegmentId={activeSegmentId}
                                    currentTimeBySegment={currentTimeBySegment}
                                    onToggleSegment={handleToggleSegment}
                                    onSeekSegment={handleSeekSegment}
                                    onAddNote={handleAddNote}
                                    editMode={editMode}
                                    onUpdateSegmentText={handleUpdateSegmentText}
                                    onUpdateSpeaker={handleUpdateSpeaker}
                                />
                            ))}
                        </div>
                    )}
                </div>


                <div className="card-panel" style={{ position: 'relative' }}>
                    <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
                        📝 Saved Notes &amp; Corrections ({notes.length})
                    </h3>

                    {/* Note save in-progress overlay */}
                    {noteSaveStatus === 'saving' && (
                        <div style={{
                            position: 'absolute',
                            inset: 0,
                            borderRadius: 'var(--radius-lg, 12px)',
                            background: 'var(--overlay-bg)',
                            backdropFilter: 'blur(4px)',
                            WebkitBackdropFilter: 'blur(4px)',
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.75rem',
                            zIndex: 10,
                            pointerEvents: 'none',
                        }}>
                            <p style={{ margin: 0, fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                                💾 Saving note…
                            </p>
                            {/* Shimmer bar */}
                            <div style={{
                                width: '160px',
                                height: '4px',
                                borderRadius: '2px',
                                background: 'var(--shimmer-bg)',
                                overflow: 'hidden',
                            }}>
                                <div style={{
                                    height: '100%',
                                    width: '40%',
                                    borderRadius: '2px',
                                    background: 'linear-gradient(90deg, transparent, var(--accent-violet), transparent)',
                                    animation: 'shimmer 1.4s ease-in-out infinite',
                                }} />
                            </div>
                        </div>
                    )}

                    {/* Note save error banner */}
                    {noteSaveStatus === 'error' && noteSaveError && (
                        <div style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.75rem',
                            padding: '0.75rem 1rem',
                            marginBottom: '1rem',
                            background: 'var(--error-bg)',
                            border: '1px solid var(--accent-rose)',
                            borderRadius: 'var(--radius-md)',
                            color: 'var(--error-text)',
                            fontSize: '0.875rem',
                        }}>
                            <span style={{ fontSize: '1.1rem', flexShrink: 0 }}>⚠️</span>
                            <div style={{ flex: 1 }}>
                                <strong>Save failed.</strong> {noteSaveError}
                            </div>
                            <button
                                onClick={() => { setNoteSaveStatus('idle'); setNoteSaveError(null); }}
                                title="Dismiss"
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: 'var(--error-text)',
                                    fontSize: '1rem',
                                    lineHeight: 1,
                                    padding: '0',
                                    flexShrink: 0,
                                }}
                            >
                                ✕
                            </button>
                        </div>
                    )}

                    <div className="notes-list" style={{ maxHeight: 'calc(70vh - 50px)' }}>
                        {notes.length === 0 ? (
                            <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textAlign: 'center', marginTop: '2rem' }}>
                                No notes recorded yet. Select text in transcription segments on the left to start.
                            </p>
                        ) : (
                            notes.map(note => (
                                <div className="note-item" key={note.id}>
                                    <div className="note-header">
                                        <span>📅 {note.date}</span>
                                        <button
                                            className="note-delete-btn"
                                            onClick={() => handleDeleteNote(note.id)}
                                            title="Delete note"
                                        >
                                            🗑️
                                        </button>
                                    </div>
                                    <div className="note-text">{note.note}</div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>

            {/* Export Options Modal */}
            {showExportModal && (
                <div className="modal-overlay" onClick={() => setShowExportModal(false)}>
                    <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{maxWidth: '480px'}}>
                        <button className="modal-close-btn" onClick={() => setShowExportModal(false)} title="Close">
                            ✕
                        </button>
                        <h3 style={{
                            marginTop: 0,
                            marginBottom: '0.5rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem'
                        }}>
                            📥 Export Options
                        </h3>
                        <p style={{fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1.25rem'}}>
                            Select the target data and file format to export for <strong>{transcriptionKey}</strong>.
                        </p>

                        <div className="setting-group" style={{marginBottom: '1.25rem'}}>
                            <label style={{
                                display: 'block',
                                fontSize: '0.95rem',
                                fontWeight: 600,
                                marginBottom: '0.6rem'
                            }}>
                                Select Content to Export
                            </label>
                            <div className="export-radio-group horizontal">
                                <label
                                    className={`export-radio-card compact ${exportTarget === 'edited_output' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="exportTarget"
                                        value="edited_output"
                                        checked={exportTarget === 'edited_output'}
                                        onChange={(e) => setExportTarget(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; Edited Output</span>
                                </label>
                                <label
                                    className={`export-radio-card compact ${exportTarget === 'notes' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="exportTarget"
                                        value="notes"
                                        checked={exportTarget === 'notes'}
                                        onChange={(e) => setExportTarget(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; Notes</span>
                                </label>
                            </div>
                        </div>

                        <div className="setting-group" style={{marginBottom: '1.25rem'}}>
                            <label style={{
                                display: 'block',
                                fontSize: '0.95rem',
                                fontWeight: 600,
                                marginBottom: '0.6rem'
                            }}>
                                Select Export Format
                            </label>
                            <div className="export-radio-group horizontal">
                                <label
                                    className={`export-radio-card compact ${exportFormat === 'json' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="exportFormat"
                                        value="json"
                                        checked={exportFormat === 'json'}
                                        onChange={(e) => setExportFormat(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; JSON</span>
                                </label>
                                <label
                                    className={`export-radio-card compact ${exportFormat === 'txt' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="exportFormat"
                                        value="txt"
                                        checked={exportFormat === 'txt'}
                                        onChange={(e) => setExportFormat(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; TXT</span>
                                </label>
                                <label
                                    className={`export-radio-card compact ${exportFormat === 'docx' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="exportFormat"
                                        value="docx"
                                        checked={exportFormat === 'docx'}
                                        onChange={(e) => setExportFormat(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; DOCX</span>
                                </label>
                            </div>
                        </div>

                        <div className="setting-group" style={{marginBottom: '1.25rem'}}>
                            <label style={{
                                display: 'block',
                                fontSize: '0.95rem',
                                fontWeight: 600,
                                marginBottom: '0.6rem'
                            }}>
                                Merge speakers
                            </label>
                            <div className="export-radio-group horizontal">
                                <label
                                    className={`export-radio-card compact ${mergedFormat === 'off' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="mergedFormat"
                                        value="off"
                                        checked={mergedFormat === 'off'}
                                        onChange={(e) => setMergedFormat(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; Off</span>
                                </label>
                                <label
                                    className={`export-radio-card compact ${mergedFormat === 'On' ? 'selected' : ''}`}>
                                    <input
                                        type="radio"
                                        name="mergedFormat"
                                        value="On"
                                        checked={mergedFormat === 'On'}
                                        onChange={(e) => setMergedFormat(e.target.value)}
                                    />
                                    <span>&nbsp;&nbsp; On</span>
                                </label>
                            </div>
                        </div>

                        <div style={{display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem'}}>
                            <button className="btn btn-secondary" onClick={() => setShowExportModal(false)}>
                                Cancel
                            </button>
                            <button className="btn btn-primary" onClick={handleDownloadExport}>
                                📥 Download File
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default Notes;