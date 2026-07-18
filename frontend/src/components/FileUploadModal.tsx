import { useState, useRef, type DragEvent } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Upload,
  X,
  File,
  Loader2,
  CheckCircle,
  XCircle,
  Archive as ArchiveIcon,
  Printer,
  Image,
  Info,
} from 'lucide-react';
import { api } from '../api/client';
import type { LibraryFileUploadResponse, PrinterProvider } from '../api/client';
import { Button } from './Button';
import { ElegooCc1StartOptions } from './ElegooCc1StartOptions';
import { isElegooCc1Printer, type ElegooCc1StartOptionsValue } from '../utils/elegooCc1';

interface UploadFile {
  file: File;
  status: 'pending' | 'uploading' | 'success' | 'error';
  error?: string;
  isZip?: boolean;
  is3mf?: boolean;
  extractedCount?: number;
}

type DirectUploadConflictStrategy = 'error' | 'rename' | 'delete_replace';

interface DirectUploadConflict {
  file: File;
  existingPath: string;
  existingSize?: number | null;
}

interface FileUploadModalProps {
  folderId: number | null;
  onClose: () => void;
  onUploadComplete: (succeededCount?: number) => void;
  /** Called after each file is successfully uploaded with its response data. Return a string to show an error and prevent modal from closing. */
  onFileUploaded?: (file: LibraryFileUploadResponse) => string | void;
  /** When true, automatically uploads the file as soon as it's added and closes the modal */
  autoUpload?: boolean;
  /** Validate files before adding. Return a string to reject with an error message. */
  validateFile?: (file: File) => string | undefined;
  /** Restrict file picker to specific file types (e.g. ".gcode,.gcode.3mf") */
  accept?: string;
  /** Human-readable description shown in the drop zone for restricted uploads. */
  acceptedFileDescription?: string;
  /** Optional printer context for backend provider-specific print-file validation. */
  uploadTargetPrinterId?: number;
  /** Upload files directly to this printer storage instead of the library. */
  directPrinterUploadId?: number;
  directPrinterProvider?: PrinterProvider;
  directPrinterModel?: string | null;
  /** Remote printer folder used for direct printer uploads. */
  directPrinterUploadPath?: string;
  /** Overwrite an existing same-name file on direct printer uploads. */
  directPrinterUploadOverwrite?: boolean;
  /** Optional notice shown in the modal before upload starts, e.g. provider-specific upload timing. */
  uploadNotice?: string;
  /** Show a direct-upload option to start printing immediately after the file lands on printer storage. */
  allowStartPrintAfterUpload?: boolean;
}

export function FileUploadModal({ folderId, onClose, onUploadComplete, onFileUploaded, autoUpload, validateFile, accept, acceptedFileDescription, uploadTargetPrinterId, directPrinterUploadId, directPrinterProvider, directPrinterModel, directPrinterUploadPath = '/', directPrinterUploadOverwrite = false, uploadNotice, allowStartPrintAfterUpload = false }: FileUploadModalProps) {
  const { t } = useTranslation();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [preserveZipStructure, setPreserveZipStructure] = useState(true);
  const [createFolderFromZip, setCreateFolderFromZip] = useState(false);
  const [generateStlThumbnails, setGenerateStlThumbnails] = useState(true);
  const [startPrintAfterUpload, setStartPrintAfterUpload] = useState(false);
  const [elegooCc1StartOptions, setElegooCc1StartOptions] = useState<ElegooCc1StartOptionsValue>({ bed_levelling: true, print_platform_type: 0 });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [directUploadConflict, setDirectUploadConflict] = useState<DirectUploadConflict | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(Array.from(e.dataTransfer.files));
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
    }
  };

  const updateFileStatus = (file: File, update: Partial<UploadFile>) => {
    setFiles((prev) => prev.map((f) => (f.file === file ? { ...f, ...update } : f)));
  };

  const findExistingDirectPrinterFile = async (file: File): Promise<DirectUploadConflict | null> => {
    if (directPrinterUploadId == null) return null;
    const response = await api.getPrinterFiles(directPrinterUploadId, directPrinterUploadPath);
    const existing = response.files.find((entry) => !entry.is_directory && entry.name === file.name);
    if (!existing) return null;
    return {
      file,
      existingPath: existing.path,
      existingSize: existing.size,
    };
  };

  const uploadFiles = async (filesToUpload: UploadFile[], conflictStrategy: DirectUploadConflictStrategy = 'error') => {
    setIsUploading(true);
    setDirectUploadConflict(null);
    let succeededCount = 0;

    for (const uf of filesToUpload) {
      if (uf.status !== 'pending') continue;

      updateFileStatus(uf.file, { status: 'uploading' });

      try {
        if (uf.isZip) {
          const result = await api.extractZipFile(uf.file, folderId, preserveZipStructure, createFolderFromZip, generateStlThumbnails);
          updateFileStatus(uf.file, {
            status: result.errors.length > 0 && result.extracted === 0 ? 'error' : 'success',
            extractedCount: result.extracted,
            error: result.errors.length > 0 ? t('fileManager.zipFilesFailed', '{{count}} files failed', { count: result.errors.length }) : undefined,
          });
          if (result.extracted > 0 || result.errors.length === 0) {
            succeededCount += 1;
          }
        } else if (directPrinterUploadId != null) {
          if (conflictStrategy === 'error') {
            const conflict = await findExistingDirectPrinterFile(uf.file);
            if (conflict) {
              updateFileStatus(uf.file, { status: 'pending' });
              setDirectUploadConflict(conflict);
              setIsUploading(false);
              return;
            }
          }
          const uploaded = await api.uploadPrinterFile(
            directPrinterUploadId,
            uf.file,
            directPrinterUploadPath,
            directPrinterUploadOverwrite,
            conflictStrategy
          );
          if (allowStartPrintAfterUpload && startPrintAfterUpload) {
            await api.startPrinterFile(
              directPrinterUploadId,
              uploaded.path,
              isElegooCc1Printer(directPrinterProvider, directPrinterModel) ? elegooCc1StartOptions : undefined
            );
          }
          updateFileStatus(uf.file, { status: 'success' });
          succeededCount += 1;
        } else {
          const result = await api.uploadLibraryFile(uf.file, folderId, generateStlThumbnails, uploadTargetPrinterId);
          updateFileStatus(uf.file, { status: 'success' });
          succeededCount += 1;
          const error = onFileUploaded?.(result);
          if (error) {
            setUploadError(error);
            setFiles([]);
            setIsUploading(false);
            return;
          }
        }
      } catch (err) {
        updateFileStatus(uf.file, {
          status: 'error',
          error: err instanceof Error ? err.message : t('fileManager.uploadFailed', 'Upload failed'),
        });
      }
    }

    setIsUploading(false);
    onUploadComplete(succeededCount);
    // #1401: don't auto-close if any file ended with an error — the user
    // needs to see the rejection message (e.g. "raw .gcode upload"), not
    // have the modal vanish before they can read it. Closing happens via
    // the X / Close button instead, after the user has seen what failed.
    setFiles((prev) => {
      const anyFailed = prev.some((f) => f.status === 'error');
      if (!anyFailed) {
        onClose();
      }
      return prev;
    });
  };

  const addFiles = (newFiles: File[]) => {
    setUploadError(null);
    if (validateFile) {
      for (const file of newFiles) {
        const error = validateFile(file);
        if (error) {
          setUploadError(error);
          return;
        }
      }
    }
    const toUpload: UploadFile[] = newFiles.map((file) => ({
      file,
      status: 'pending' as const,
      isZip: file.name.toLowerCase().endsWith('.zip'),
      is3mf: file.name.toLowerCase().endsWith('.3mf'),
    }));
    setFiles((prev) => [...prev, ...toUpload]);

    if (autoUpload && newFiles.length > 0) {
      uploadFiles(toUpload);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const hasZipFiles = files.some((f) => f.isZip && f.status === 'pending');
  const hasStlFiles = files.some((f) => f.file.name.toLowerCase().endsWith('.stl') && f.status === 'pending');
  const has3mfFiles = files.some((f) => f.is3mf && f.status === 'pending');
  const pendingCount = files.filter((f) => f.status === 'pending').length;
  const allDone = files.length > 0 && pendingCount === 0 && !isUploading;
  const uploadButtonLabel = allowStartPrintAfterUpload && startPrintAfterUpload
    ? t('common.uploadAndPrint', 'Upload & Print')
    : t('common.upload');
  const conflictingUploadFile = directUploadConflict
    ? files.find((f) => f.file === directUploadConflict.file)
    : undefined;
  const continueDirectConflictUpload = (strategy: Exclude<DirectUploadConflictStrategy, 'error'>) => {
    if (!conflictingUploadFile) return;
    uploadFiles([conflictingUploadFile], strategy);
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-bambu-dark-secondary rounded-lg w-full max-w-lg border border-bambu-dark-tertiary">
        <div className="p-4 border-b border-bambu-dark-tertiary flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{t('fileManager.uploadFiles')}</h2>
          <button onClick={onClose} className="p-1 hover:bg-bambu-dark rounded">
            <X className="w-5 h-5 text-bambu-gray" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Drop Zone */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              isDragging
                ? 'border-bambu-green bg-bambu-green/10'
                : 'border-bambu-dark-tertiary hover:border-bambu-green/50'
            }`}
          >
            <Upload className={`w-10 h-10 mx-auto mb-3 ${isDragging ? 'text-bambu-green' : 'text-bambu-gray'}`} />
            <p className="text-white font-medium">
              {isDragging ? t('fileManager.dropFilesHere') : t('fileManager.dragDropFiles')}
            </p>
            <p className="text-sm text-bambu-gray mt-1">{t('fileManager.orClickToBrowse')}</p>
            <p className="text-xs text-bambu-gray/70 mt-2">{acceptedFileDescription ?? t('fileManager.allFileTypesSupported')}</p>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={accept}
            className="hidden"
            onChange={handleFileSelect}
          />

          {allowStartPrintAfterUpload && directPrinterUploadId != null && (
            <label className="flex items-center gap-2 cursor-pointer rounded-lg border border-bambu-dark-tertiary bg-bambu-dark/40 p-3">
              <input
                type="checkbox"
                checked={startPrintAfterUpload}
                onChange={(e) => setStartPrintAfterUpload(e.target.checked)}
                className="w-4 h-4 rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
              />
              <span className="text-sm text-white">Start print after upload</span>
            </label>
          )}

          {allowStartPrintAfterUpload &&
            startPrintAfterUpload &&
            isElegooCc1Printer(directPrinterProvider, directPrinterModel) && (
              <ElegooCc1StartOptions value={elegooCc1StartOptions} onChange={setElegooCc1StartOptions} />
            )}

          {uploadNotice && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
              <div className="flex items-start gap-3">
                <Info className="w-5 h-5 text-amber-400 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-amber-200">{uploadNotice}</p>
              </div>
            </div>
          )}

          {directUploadConflict && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
              <div className="flex items-start gap-3">
                <Info className="w-5 h-5 text-amber-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 space-y-3">
                  <div>
                    <p className="text-sm text-amber-100 font-medium">
                      {directUploadConflict.file.name} already exists on the printer USB.
                    </p>
                    <p className="text-xs text-amber-200/80 mt-1">
                      Choose whether to upload it as a renamed copy, delete the existing file first, or cancel.
                    </p>
                  </div>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <Button
                      type="button"
                      variant="primary"
                      size="sm"
                      onClick={() => continueDirectConflictUpload('rename')}
                      disabled={isUploading}
                    >
                      Upload as copy
                    </Button>
                    <Button
                      type="button"
                      variant="danger"
                      size="sm"
                      onClick={() => continueDirectConflictUpload('delete_replace')}
                      disabled={isUploading}
                    >
                      Delete existing and upload
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      onClick={() => setDirectUploadConflict(null)}
                      disabled={isUploading}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ZIP Options */}
          {hasZipFiles && (
            <div className="p-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
              <div className="flex items-start gap-3">
                <ArchiveIcon className="w-5 h-5 text-blue-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm text-blue-300 font-medium">{t('fileManager.zipFilesDetected')}</p>
                  <p className="text-xs text-blue-300/70 mt-1">
                    {t('fileManager.zipExtractOptions')}
                  </p>
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={preserveZipStructure}
                      onChange={(e) => setPreserveZipStructure(e.target.checked)}
                      className="w-4 h-4 rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
                    />
                    <span className="text-sm text-white">{t('fileManager.preserveZipStructure')}</span>
                  </label>
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createFolderFromZip}
                      onChange={(e) => setCreateFolderFromZip(e.target.checked)}
                      className="w-4 h-4 rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
                    />
                    <span className="text-sm text-white">{t('fileManager.createFolderFromZip')}</span>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* 3MF File Info */}
          {has3mfFiles && (
            <div className="p-3 bg-purple-500/10 border border-purple-500/30 rounded-lg">
              <div className="flex items-start gap-3">
                <Printer className="w-5 h-5 text-purple-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm text-purple-300 font-medium">{t('fileManager.threemfDetected')}</p>
                  <p className="text-xs text-purple-300/70 mt-1">
                    {t('fileManager.threemfExtractionInfo')}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* STL Thumbnail Options */}
          {(hasStlFiles || hasZipFiles) && (
            <div className="p-3 bg-bambu-green/10 border border-bambu-green/30 rounded-lg">
              <div className="flex items-start gap-3">
                <Image className="w-5 h-5 text-bambu-green mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm text-bambu-green font-medium">{t('fileManager.stlThumbnailGeneration')}</p>
                  <p className="text-xs text-bambu-green/70 mt-1">
                    {hasZipFiles && !hasStlFiles
                      ? t('fileManager.zipMayContainStl')
                      : t('fileManager.thumbnailsCanBeGenerated')}
                  </p>
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={generateStlThumbnails}
                      onChange={(e) => setGenerateStlThumbnails(e.target.checked)}
                      className="w-4 h-4 rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
                    />
                    <span className="text-sm text-white">{t('fileManager.generateThumbnailsForStl')}</span>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* File List */}
          {files.length > 0 && (
            <div className="max-h-48 overflow-y-auto space-y-2">
              {files.map((uploadFile, index) => (
                <div
                  key={index}
                  className="flex items-center gap-3 p-2 bg-bambu-dark rounded-lg"
                >
                  {uploadFile.isZip ? (
                    <ArchiveIcon className="w-4 h-4 text-blue-400 flex-shrink-0" />
                  ) : (
                    <File className="w-4 h-4 text-bambu-gray flex-shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white truncate">{uploadFile.file.name}</p>
                    <p className="text-xs text-bambu-gray">
                      {(uploadFile.file.size / 1024 / 1024).toFixed(2)} MB
                      {uploadFile.isZip && uploadFile.status === 'pending' && (
                        <span className="text-blue-400 ml-2">• {t('fileManager.willBeExtracted')}</span>
                      )}
                      {uploadFile.extractedCount !== undefined && (
                        <span className="text-green-400 ml-2">• {t('fileManager.filesExtracted', { count: uploadFile.extractedCount })}</span>
                      )}
                    </p>
                    {/* #1401: errors render inline rather than as a hover-only
                        title. The backend's rejection messages explain the
                        actual fix (re-export as .gcode.3mf) — useless if the
                        user can't read them. */}
                    {uploadFile.status === 'error' && uploadFile.error && (
                      <p className="text-xs text-red-400 mt-1 break-words">{uploadFile.error}</p>
                    )}
                  </div>
                  {uploadFile.status === 'pending' && (
                    <button
                      onClick={() => removeFile(index)}
                      className="p-1 hover:bg-bambu-dark-tertiary rounded"
                    >
                      <X className="w-4 h-4 text-bambu-gray" />
                    </button>
                  )}
                  {uploadFile.status === 'uploading' && (
                    <Loader2 className="w-4 h-4 text-bambu-green animate-spin" />
                  )}
                  {uploadFile.status === 'success' && (
                    <CheckCircle className="w-4 h-4 text-green-500" />
                  )}
                  {uploadFile.status === 'error' && (
                    <span title={uploadFile.error}>
                      <XCircle className="w-4 h-4 text-red-500" />
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Compatibility Error */}
          {uploadError && (
            <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
              <div className="flex items-start gap-3">
                <XCircle className="w-5 h-5 text-red-400 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-red-300">{uploadError}</p>
              </div>
            </div>
          )}
        </div>

        <div className="p-4 border-t border-bambu-dark-tertiary flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          {!allDone && (
            <Button
              onClick={() => uploadFiles(files)}
              disabled={pendingCount === 0 || isUploading}
            >
              {isUploading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  {t('fileManager.uploading')}
                </>
              ) : (
                <>
                  <Upload className="w-4 h-4 mr-2" />
                  {uploadButtonLabel} {pendingCount > 0 ? `(${pendingCount})` : ''}
                </>
              )}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
