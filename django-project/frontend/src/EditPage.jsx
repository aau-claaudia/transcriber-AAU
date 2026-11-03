import { apiFetch as fetch } from './api.js';
import React, { useState, useEffect } from 'react';

const EditPage = ({ transcriptionKey, transcriptionData, onBack, onOpenNotes, onServerError}) => {
    const [notes, setNotes] = useState([]);
    const { logFiles, zipFile } = transcriptionData || {};

    // Load notes from server on mount / key change
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
                setNotes(data.notes ?? []);
            })
            .catch(err => {
                console.error('Failed to load notes from server:', err);
                setNotes([]);
                onServerError();
            });
    }, [transcriptionData?.name]);


    // Delete note — optimistic removal with server sync
    const handleDeleteNote = (noteId) => {
        const dirName = transcriptionData?.name;
        if (!dirName) return;

        const previousNotes = notes;
        setNotes(prev => prev.filter(note => note.id !== noteId));

        fetch('/delete-note/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dir_name: dirName, note_id: noteId }),
        })
            .then(res => {
                if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
            })
            .catch(err => {
                console.error('Failed to delete note on server:', err);
                // Roll back on failure
                setNotes(previousNotes);
                onServerError();
            });
    };

    const getFileExtension = (fileName) => {
        const specialCases = ['dote.json'];
        for (const ext of specialCases) {
            if (fileName.endsWith(ext)) {
                return ext;
            }
        }
        return fileName.split('.').pop();
    };

    const extensionToolTip = new Map();
    extensionToolTip.set('aud', 'A subtitle-like format used by INRS-Telecom');
    extensionToolTip.set('csv', 'Comma-separated value format used for spreadsheets');
    extensionToolTip.set('docx', 'Word document format');
    extensionToolTip.set('dote.json', 'AAU based JSON transcription format: Distributed Open Transcription Environment');
    extensionToolTip.set('json', 'JSON output file containing full detailed transcription metadata');
    extensionToolTip.set('srt', 'SubRip Subtitle (SRT) format');
    extensionToolTip.set('tsv', 'Tab-separated values tabular data');
    extensionToolTip.set('txt', 'A simple text file format without speaker segments');
    extensionToolTip.set('vtt', 'WebVTT subtitle and captioning format');

    const getTitleForFileExtension = (extension) => {
        return extensionToolTip.get(extension) || 'Download transcription file';
    };

    const hasStandardFiles = transcriptionData?.files?.length > 0;
    const hasMergedFiles = transcriptionData?.mergedFiles?.length > 0;

    return (
        <div className="edit-page" style={{ animation: 'fadeIn 0.4s ease-out' }}>
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                </div>
                <h2 style={{ margin: 0, fontSize: '1.5rem' }}>Results: {transcriptionKey}</h2>
            </div>

            <div className="edit-page-layout">
                {/* Left Column: Results Download */}
                <div className="card-panel">
                    <h3 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem', marginBottom: '1.5rem' }}>
                        🎙️ Transcription Results
                    </h3>

                    <div style={{ marginBottom: '1.5rem' }}>
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                            Click on any format card below to download the transcribed file.
                        </p>
                    </div>

                    {hasStandardFiles && (
                        <div style={{ marginBottom: '2rem' }}>
                            <h3>Standard Outputs</h3>
                            <div className="download-grid">
                                {transcriptionData.files.map((file, idx) => {
                                    const ext = getFileExtension(file.file_name);
                                    return (
                                        <a
                                            key={idx}
                                            href={file.file_url}
                                            className="download-btn-card"
                                            title={getTitleForFileExtension(ext)}
                                            rel="noreferrer"
                                        >
                                            <span className="ext-badge">{ext}</span>
                                            <span className="ext-desc">{getTitleForFileExtension(ext).slice(0, 30)}...</span>
                                        </a>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {hasMergedFiles && (
                        <div style={{ marginBottom: '2rem' }}>
                            <h3>Merged Speaker Formats</h3>
                            <div className="download-grid">
                                {transcriptionData.mergedFiles.map((file, idx) => {
                                    const ext = getFileExtension(file.file_name);
                                    return (
                                        <a
                                            key={idx}
                                            href={file.file_url}
                                            className="download-btn-card"
                                            title={getTitleForFileExtension(ext)}
                                            rel="noreferrer"
                                        >
                                            <span className="ext-badge">{ext}</span>
                                            <span className="ext-desc">{getTitleForFileExtension(ext).slice(0, 30)}...</span>
                                        </a>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* Log & Zip section in Edit Page for contextual convenience */}
                    {zipFile && (
                        <div style={{
                            marginTop: '2rem',
                            padding: '1rem',
                            background: 'rgba(255,255,255,0.01)',
                            borderRadius: 'var(--radius-md)',
                            border: '1px solid var(--border-color)'
                        }}>
                            <h4 style={{ marginBottom: '0.5rem' }}>📦 Entire Output Archive</h4>
                            <p style={{ fontSize: '0.85rem', marginBottom: '0.75rem' }}>Download a zip archive containing all
                                format outputs for this transcription.</p>
                            <a href={zipFile.file_url} className="btn btn-secondary">
                                Download Zip File
                            </a>
                        </div>
                    )}
                    {logFiles && logFiles.length > 0 && (
                        <div style={{
                            marginTop: '2rem',
                            padding: '1rem',
                            background: 'rgba(255,255,255,0.01)',
                            borderRadius: 'var(--radius-md)',
                            border: '1px solid var(--border-color)'
                        }}>
                            <h4 style={{ marginBottom: '0.5rem' }}>Log Files</h4>
                            <p style={{ fontSize: '0.85rem', marginBottom: '0.75rem' }}>Download log files from the
                                transcription process.</p>
                            {logFiles.map((file, idx) => {
                                return (
                                    <a
                                        style={{ marginRight: '1rem' }}
                                        key={idx}
                                        href={file.file_url} className="btn btn-secondary">
                                        {file.file_name}
                                    </a>
                                );
                            })
                            }
                        </div>
                    )}
                </div>

                {/* Right Column: Notes & Annotation System */}
                <div className="card-panel">
                    <div className="notes-container">
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem', marginBottom: '1rem' }}>
                            <h3 style={{ margin: 0 }}>📝 Notes & Annotation</h3>
                            <button className="btn btn-primary" onClick={onOpenNotes} style={{ padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}>
                                📝 Edits & Notes
                            </button>
                        </div>
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: '1rem' }}>
                            Click "Handle Notes" above to add new corrective notes or to edit the generated transcription output.
                        </p>

                        <hr style={{ border: 'none', borderBottom: '1px solid var(--border-color)', margin: '1rem 0' }} />

                        <h3>Saved Notes ({notes.length})</h3>
                        <div className="notes-list" style={{ maxHeight: 'calc(70vh - 50px)' }}>
                            {notes.length === 0 ? (
                                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', textAlign: 'center', marginTop: '1rem' }}>
                                    No notes recorded yet.
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
            </div>
        </div>
    );
};

export default EditPage;
