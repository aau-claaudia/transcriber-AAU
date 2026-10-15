import React from 'react';

const Settings = ({onUpdateModel, currentModelSize, availableMemory, transcriptionModels, onUpdateLanguage, currentLanguage,
    resourceProfiles, resourceProfile, onUpdateResourceProfile}) => {
    // Function to handle model change
    const handleModelChange = (event) => {
        onUpdateModel(event.target.value);
    };

    // Function to handle model change
    const handleLangaugeChange = (event) => {
        onUpdateLanguage(event.target.value);
    };

    return (
        <div>
            <h2 style={{ marginBottom: '1.5rem', fontFamily: 'Outfit' }}>Settings</h2>
            <div className="setting-group">
                <h3>Compute resources</h3>
                <div className="select-box">
                    <select aria-label="Compute resources" value={resourceProfile}
                        onChange={event => onUpdateResourceProfile(event.target.value)}>
                        {Object.entries(resourceProfiles ?? {}).map(([identifier, profile]) => (
                            <option key={identifier} value={identifier}>{profile.label ?? identifier}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Section for setting a model */}
            <div className="setting-group">
                <h3>Select model</h3>
                <div className="select-box">
                    <select defaultValue={currentModelSize} onChange={handleModelChange}>
                        {Object.entries(transcriptionModels).map(([modelName, memoryReq]) => {
                            return <option key={modelName} value={modelName}>{modelName}</option>;
                        })}
                    </select>
                </div>
                {transcriptionModels[currentModelSize] > availableMemory && (
                    <div className="memory-warning">
                        ⚠️ Warning: It is recommended to run transcriber on a machine type with at least 16 cores / 64 GB of RAM. Using this model on a small machine may result in slow transcription and/or running out of memory.
                    </div>
                )}
            </div>

            <div style={{ borderBottom: '1px solid var(--border-color)', margin: '1.5rem 0' }}></div>

            {/* Section for setting a language */}
            <div className="setting-group">
                <h3>Select language</h3>
                <div className="select-box">
                    <select
                        value={currentModelSize === "nvidia/parakeet-tdt-0.6b-v3" ? "auto" : currentLanguage}
                        disabled={currentModelSize === "nvidia/parakeet-tdt-0.6b-v3"}
                        onChange={handleLangaugeChange}
                    >
                        <option value="auto">Automatic</option>
                        <option value="af">Afrikaans</option>
                        <option value="sq">Albanian</option>
                        <option value="am">Amharic</option>
                        <option value="ar">Arabic</option>
                        <option value="hy">Armenian</option>
                        <option value="as">Assamese</option>
                        <option value="az">Azerbaijani</option>
                        <option value="ba">Bashkir</option>
                        <option value="eu">Basque</option>
                        <option value="be">Belarusian</option>
                        <option value="bn">Bengali</option>
                        <option value="bs">Bosnian</option>
                        <option value="br">Breton</option>
                        <option value="bg">Bulgarian</option>
                        <option value="ca">Catalan</option>
                        <option value="zh">Chinese</option>
                        <option value="hr">Croatian</option>
                        <option value="cs">Czech</option>
                        <option value="da">Danish</option>
                        <option value="nl">Dutch</option>
                        <option value="en">English</option>
                        <option value="et">Estonian</option>
                        <option value="fo">Faroese</option>
                        <option value="fi">Finnish</option>
                        <option value="fr">French</option>
                        <option value="ka">Georgian</option>
                        <option value="de">German</option>
                        <option value="gl">Galician</option>
                        <option value="el">Greek</option>
                        <option value="gu">Gujarati</option>
                        <option value="ht">Haitian creole</option>
                        <option value="ha">Hausa</option>
                        <option value="haw">Hawaiian</option>
                        <option value="he">Hebrew</option>
                        <option value="hi">Hindi</option>
                        <option value="hu">Hungarian</option>
                        <option value="id">Indonesian</option>
                        <option value="is">Icelandic</option>
                        <option value="it">Italian</option>
                        <option value="ja">Japanese</option>
                        <option value="jw">Javanese</option>
                        <option value="kn">Kannada</option>
                        <option value="kk">Kazakh</option>
                        <option value="km">Khmer</option>
                        <option value="ko">Korean</option>
                        <option value="lo">Lao</option>
                        <option value="la">Latin</option>
                        <option value="lv">Latvian</option>
                        <option value="ln">Lingala</option>
                        <option value="lt">Lithuanian</option>
                        <option value="lb">Luxembourgish</option>
                        <option value="mk">Macedonian</option>
                        <option value="mg">Malagasy</option>
                        <option value="ms">Malay</option>
                        <option value="ml">Malayalam</option>
                        <option value="mt">Maltese</option>
                        <option value="mi">Maori</option>
                        <option value="mr">Marathi</option>
                        <option value="mn">Mongolian</option>
                        <option value="my">Myanmar</option>
                        <option value="ne">Nepali</option>
                        <option value="no">Norwegian</option>
                        <option value="nn">Nynorsk</option>
                        <option value="oc">Occitan</option>
                        <option value="ps">Pashto</option>
                        <option value="fa">Persian</option>
                        <option value="pl">Polish</option>
                        <option value="pt">Portuguese</option>
                        <option value="pa">Punjabi</option>
                        <option value="ro">Romanian</option>
                        <option value="ru">Russian</option>
                        <option value="sa">Sanskrit</option>
                        <option value="sr">Serbian</option>
                        <option value="sn">Shona</option>
                        <option value="si">Sinhala</option>
                        <option value="sd">Sindhi</option>
                        <option value="sk">Slovak</option>
                        <option value="sl">Slovenian</option>
                        <option value="so">Somali</option>
                        <option value="es">Spanish</option>
                        <option value="su">Sundanese</option>
                        <option value="sw">Swahili</option>
                        <option value="sv">Swedish</option>
                        <option value="tl">Tagalog</option>
                        <option value="tg">Tajik</option>
                        <option value="ta">Tamil</option>
                        <option value="tt">Tatar</option>
                        <option value="te">Telugu</option>
                        <option value="th">Thai</option>
                        <option value="bo">Tibetan</option>
                        <option value="tr">Turkish</option>
                        <option value="tk">Turkmen</option>
                        <option value="uk">Ukrainian</option>
                        <option value="ur">Urdu</option>
                        <option value="uz">Uzbek</option>
                        <option value="vi">Vietnamese</option>
                        <option value="cy">Welsh</option>
                        <option value="yi">Yiddish</option>
                        <option value="yo">Yoruba</option>
                    </select>
                </div>
            </div>
        </div>
    );
};

export default Settings;