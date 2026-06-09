#lang racket

;; Pruebas unitarias formales para complementar el benchmark integral.

(require rackunit
         racket/draw
         racket/runtime-path
         "mainbase.rkt"
         "filtrossecuenciales.rkt"
         "filtrosrecursivos.rkt"
         "filtrosparalelos.rkt")

(define-runtime-path BASE-DIR ".")

(struct filter-case (name sequential parallel recursive convolution?) #:transparent)

(define filters
  (list
   (filter-case "grayscale" grayscale-sequential! grayscale-parallel grayscale-recursive #f)
   (filter-case "sepia" sepia-sequential! sepia-parallel sepia-recursive #f)
   (filter-case "negative" negative-sequential! negative-parallel negative-recursive #f)
   (filter-case "edge" edge-sequential! edge-parallel edge-recursive #t)
   (filter-case "gaussian" gaussian-sequential! gaussian-parallel gaussian-recursive #t)))

(define (load-image-bytes image-name)
  (define bmp (make-object bitmap% (build-path BASE-DIR image-name)))
  (check-true (send bmp ok?) (format "La imagen ~a debe cargar" image-name))
  (define w (send bmp get-width))
  (define h (send bmp get-height))
  (define pixels (make-bytes (* w h 4)))
  (send bmp get-argb-pixels 0 0 w h pixels)
  (values pixels w h))

(define (apply-sequential spec input w h)
  (define buf (bytes-copy input))
  (if (filter-case-convolution? spec)
      ((filter-case-sequential spec) buf w h)
      ((filter-case-sequential spec) buf))
  buf)

(define (apply-parallel spec input w h workers)
  (set-num-workers! workers)
  (define buf (bytes-copy input))
  (if (filter-case-convolution? spec)
      ((filter-case-parallel spec) buf w h)
      ((filter-case-parallel spec) buf)))

(define (apply-recursive spec input w h)
  (define buf (bytes-copy input))
  (if (filter-case-convolution? spec)
      ((filter-case-recursive spec) buf w h)
      ((filter-case-recursive spec) buf)))

(define-values (cat-bytes cat-w cat-h) (load-image-bytes "cat.png"))

(for ([spec filters])
  (define expected (apply-sequential spec cat-bytes cat-w cat-h))
  (test-case (format "~a: paralelo equivale a secuencial con 1, 2, 4, 8 y 16 workers"
                     (filter-case-name spec))
    (for ([workers '(1 2 4 8 16)])
      (check-true
       (bytes=? expected (apply-parallel spec cat-bytes cat-w cat-h workers))
       (format "~a falla con ~a workers" (filter-case-name spec) workers))))
  (test-case (format "~a: recursivo equivale a secuencial" (filter-case-name spec))
    (check-true (bytes=? expected (apply-recursive spec cat-bytes cat-w cat-h)))))

(test-case "process-request procesa un caso valido"
  (define-values (b64 ms)
    (process-request "cat.png" "edge" "parallel" #:workers 4))
  (check-true (> (string-length b64) 1000))
  (check-true (real? ms)))

(test-case "process-request rechaza imagen inexistente"
  (define-values (b64 ms)
    (process-request "no-existe.png" "negative" "sequential"))
  (check-equal? b64 "")
  (check-equal? ms 0))

(displayln "pruebas-unitarias: OK")
