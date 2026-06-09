#lang racket

;; verificacion-benchmarks.rkt
;; Ejecuta pruebas reproducibles de correctitud y rendimiento para Evidencia 2.
;; Genera:
;;   - benchmark-resultados.csv
;;   - salidas/<imagen>_<filtro>.png

(require racket/draw
         racket/format
         racket/list
         "filtrossecuenciales.rkt"
         "filtrosrecursivos.rkt"
         "filtrosparalelos.rkt")

(struct filter-spec (name sequential parallel recursive convolution?) #:transparent)

(define images
  '("cat.png"
    "cats2.png"
    "new-york-large.jpg"))

(define worker-counts '(1 2 4 8 16))

(define filters
  (list
   (filter-spec "grayscale" grayscale-sequential! grayscale-parallel grayscale-recursive #f)
   (filter-spec "sepia" sepia-sequential! sepia-parallel sepia-recursive #f)
   (filter-spec "negative" negative-sequential! negative-parallel negative-recursive #f)
   (filter-spec "edge" edge-sequential! edge-parallel edge-recursive #t)
   (filter-spec "gaussian" gaussian-sequential! gaussian-parallel gaussian-recursive #t)))

(define (csv-quote v)
  (define s (~a v))
  (if (regexp-match? #rx"[,\"\n]" s)
      (format "\"~a\"" (regexp-replace* #rx"\"" s "\"\""))
      s))

(define (write-csv-row out row)
  (fprintf out "~a\n" (string-join (map csv-quote row) ",")))

(define (load-image-bytes image-name)
  (define bmp (make-object bitmap% image-name))
  (define w (send bmp get-width))
  (define h (send bmp get-height))
  (define pixels (make-bytes (* w h 4)))
  (send bmp get-argb-pixels 0 0 w h pixels)
  (values pixels w h))

(define (base-name image-name)
  (regexp-replace #rx"\\.[^.]+$" image-name ""))

(define (save-output-image! image-name filter-name w h pixels)
  (make-directory* "salidas")
  (define bmp (make-object bitmap% w h))
  (send bmp set-argb-pixels 0 0 w h pixels)
  (define out-path (build-path "salidas" (format "~a_~a.png" (base-name image-name) filter-name)))
  (send bmp save-file out-path 'png))

(define (checksum bytes-buf)
  ;; FNV-1a de 32 bits. Sirve para detectar cambios accidentales en salidas.
  (for/fold ([acc 2166136261])
            ([b (in-bytes bytes-buf)])
    (modulo (* (bitwise-xor acc b) 16777619) 4294967296)))

(define (apply-filter method spec input-bytes w h workers)
  (define buf (bytes-copy input-bytes))
  (cond
    [(eq? method 'sequential)
     (if (filter-spec-convolution? spec)
         ((filter-spec-sequential spec) buf w h)
         ((filter-spec-sequential spec) buf))
     buf]
    [(eq? method 'parallel)
     (set-num-workers! workers)
     (if (filter-spec-convolution? spec)
         ((filter-spec-parallel spec) buf w h)
         ((filter-spec-parallel spec) buf))]
    [(eq? method 'recursive)
     (if (filter-spec-convolution? spec)
         ((filter-spec-recursive spec) buf w h)
         ((filter-spec-recursive spec) buf))]
    [else (error 'apply-filter "Metodo no reconocido: ~a" method)]))

(define (measurement-repetitions pixels)
  (cond
    [(<= pixels 50000) 30]
    [(<= pixels 1500000) 3]
    [else 1]))

(define (recursive-repetitions pixels)
  (cond
    [(<= pixels 50000) 5]
    [(<= pixels 1500000) 1]
    [else 0]))

(define (measure thunk repetitions)
  (collect-garbage)
  (define start (current-inexact-milliseconds))
  (define last-result
    (for/fold ([last #f])
              ([_ (in-range repetitions)])
      (thunk)))
  (define elapsed (- (current-inexact-milliseconds) start))
  (values elapsed (/ elapsed repetitions) last-result))

(define (emit-result out image-name w h spec method workers repetitions elapsed per-run ok? result)
  (write-csv-row
   out
   (list image-name
         w
         h
         (* w h)
         (filter-spec-name spec)
         method
         (or workers "")
         repetitions
         (~r elapsed #:precision 3)
         (~r per-run #:precision 3)
         ok?
         (checksum result))))

(define (main)
  (printf "CPU logicos reportados por Racket: ~a\n" (processor-count))
  (call-with-output-file
    "benchmark-resultados.csv"
    #:exists 'replace
    (lambda (out)
      (write-csv-row out
                     '("image" "width" "height" "pixels" "filter" "method"
                       "workers" "repetitions" "elapsed_ms" "ms_per_run"
                       "matches_sequential" "checksum"))
      (for ([image-name images])
        (define-values (input-bytes w h) (load-image-bytes image-name))
        (define pixels (* w h))
        (define reps (measurement-repetitions pixels))
        (define rec-reps (recursive-repetitions pixels))
        (printf "Imagen ~a (~ax~a, ~a pixeles), reps=~a\n" image-name w h pixels reps)
        (for ([spec filters])
          (printf "  Filtro ~a\n" (filter-spec-name spec))
          (define expected (apply-filter 'sequential spec input-bytes w h #f))
          (save-output-image! image-name (filter-spec-name spec) w h expected)

          (define-values (seq-total seq-per seq-last)
            (measure (lambda () (apply-filter 'sequential spec input-bytes w h #f)) reps))
          (emit-result out image-name w h spec "sequential" "" reps seq-total seq-per
                       (bytes=? expected seq-last) seq-last)

          (when (> rec-reps 0)
            (define-values (rec-total rec-per rec-last)
              (measure (lambda () (apply-filter 'recursive spec input-bytes w h #f)) rec-reps))
            (emit-result out image-name w h spec "recursive" "" rec-reps rec-total rec-per
                         (bytes=? expected rec-last) rec-last))

          (for ([workers worker-counts])
            (define probe (apply-filter 'parallel spec input-bytes w h workers))
            (define ok? (bytes=? expected probe))
            (define-values (par-total par-per par-last)
              (measure (lambda () (apply-filter 'parallel spec input-bytes w h workers)) reps))
            (emit-result out image-name w h spec "parallel" workers reps par-total par-per
                         (and ok? (bytes=? expected par-last)) par-last))))))
  (printf "Listo: benchmark-resultados.csv y carpeta salidas/ generados.\n"))

(module+ main
  (main))
