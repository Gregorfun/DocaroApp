<?php
// ===============================
// Einstellungen
// ===============================

// Zielordner für Uploads (voller Pfad relativ zu diesem Script)
$uploadDir = __DIR__ . '/eingang/';

// Max. Dateigröße (hier 20 MB)
$maxFileSize = 20 * 1024 * 1024; // 20 MB in Bytes

// Fehlermeldungen sammeln
$messages = [];

// Wurde ein Upload abgesendet?
if ($_SERVER['REQUEST_METHOD'] === 'POST') {

    if (!isset($_FILES['files'])) {
        $messages[] = "Keine Datei empfangen.";
    } else {
        $files = $_FILES['files'];

        // Mehrere Dateien möglich
        for ($i = 0; $i < count($files['name']); $i++) {
            $name     = $files['name'][$i];
            $type     = $files['type'][$i];
            $tmpName  = $files['tmp_name'][$i];
            $error    = $files['error'][$i];
            $size     = $files['size'][$i];

            if ($error !== UPLOAD_ERR_OK) {
                $messages[] = "Fehler beim Upload von '$name' (Error-Code: $error).";
                continue;
            }

            // Dateigröße prüfen
            if ($size > $maxFileSize) {
                $messages[] = "Datei '$name' ist größer als das erlaubte Limit von 20 MB.";
                continue;
            }

            // Nur PDF erlauben (Endung + grober MIME-Check)
            $extension = strtolower(pathinfo($name, PATHINFO_EXTENSION));
            if ($extension !== 'pdf') {
                $messages[] = "Datei '$name' ist kein PDF (Endung: .$extension).";
                continue;
            }

            // Zielpfad bauen (unsichere Zeichen ersetzen)
            $safeName = preg_replace('/[^a-zA-Z0-9_\-\.]/', '_', $name);
            $targetPath = $uploadDir . $safeName;

            // Eindeutigen Namen finden, falls Datei existiert
            $counter = 1;
            while (file_exists($targetPath)) {
                $fileBase = pathinfo($safeName, PATHINFO_FILENAME);
                $fileExt  = pathinfo($safeName, PATHINFO_EXTENSION);
                $targetPath = $uploadDir . $fileBase . '_' . $counter . '.' . $fileExt;
                $counter++;
            }

            if (!is_dir($uploadDir)) {
                if (!mkdir($uploadDir, 0755, true)) {
                    $messages[] = "Upload-Ordner konnte nicht erstellt werden.";
                    break;
                }
            }

            if (!move_uploaded_file($tmpName, $targetPath)) {
                $messages[] = "Konnte Datei '$name' nicht nach '$targetPath' verschieben.";
                continue;
            }

            $messages[] = "Datei '$name' wurde als '" . basename($targetPath) . "' hochgeladen.";
        }
    }
}
?>
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Lieferscheine Upload</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 2rem;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            padding: 1.5rem 2rem;
            border-radius: 8px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.1);
        }
        h1 {
            font-size: 1.5rem;
            margin-bottom: 1rem;
        }
        .messages {
            margin-bottom: 1rem;
        }
        .messages p {
            margin: 0.3rem 0;
            padding: 0.4rem 0.6rem;
            border-radius: 4px;
            background: #eef;
        }
        .messages p.error {
            background: #fee;
            color: #a00;
        }
        .field {
            margin-bottom: 1rem;
        }
        button {
            padding: 0.6rem 1.2rem;
            font-size: 1rem;
            border: none;
            border-radius: 4px;
            background: #0078d4;
            color: white;
            cursor: pointer;
        }
        button:hover {
            background: #005ea3;
        }
        code {
            background: #eee;
            padding: 0 4px;
            border-radius: 3px;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>Lieferscheine hochladen</h1>

    <p>Wähle eine oder mehrere PDF-Dateien aus. Sie werden in den Ordner
        <code>eingang/</code> auf dem Server gespeichert.</p>

    <div class="messages">
        <?php if (!empty($messages)): ?>
            <?php foreach ($messages as $msg): ?>
                <?php
                $isError = (
                    stripos($msg, 'Fehler') !== false ||
                    stripos($msg, 'kein PDF') !== false ||
                    stripos($msg, 'größer als') !== false ||
                    stripos($msg, 'nicht erstellt') !== false
                );
                ?>
                <p class="<?php echo $isError ? 'error' : ''; ?>">
                    <?php echo htmlspecialchars($msg, ENT_QUOTES, 'UTF-8'); ?>
                </p>
            <?php endforeach; ?>
        <?php endif; ?>
    </div>

    <form action="" method="post" enctype="multipart/form-data">
        <div class="field">
            <label for="fileInput">PDF-Dateien auswählen:</label><br>
            <input type="file" id="fileInput" name="files[]" accept="application/pdf" multiple required>
        </div>
        <button type="submit">Hochladen</button>
    </form>

    <p style="margin-top:1rem; font-size:0.9rem; color:#555;">
        Hinweis: Max. 20 MB pro Datei. Nur PDFs werden akzeptiert.
    </p>
</div>
</body>
</html>
