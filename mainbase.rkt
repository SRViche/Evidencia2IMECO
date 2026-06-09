#lang racket

; mainbase.rkt
; Autores: Ivan Burrola, Alberto Lopez, Axel Lugo, Sebastian Viche
; Materia: Implementacion de metodos computacionales

(require racket/draw)
(require racket/runtime-path)
(require "filtrossecuenciales.rkt")
(require "filtrosrecursivos.rkt")
(require "filtrosparalelos.rkt")
(require (prefix-in b64: net/base64))

(define-runtime-path BASE-DIR ".")

(provide process-request)

;; workers-count : exact-integer? — número de hilos para filtros paralelos.
;; Se aplica justo antes de ejecutar el filtro.
(define (process-request image-name filter-name method-name
                          #:workers [workers-count #f])

  ;; Aplicar número de workers si se especificó y el método es paralelo
  (when (and workers-count (equal? method-name "parallel"))
    (set-num-workers! workers-count))

  ;; 1. Cargar imagen
  (define image-path (build-path BASE-DIR image-name))
  (define bmp
    (with-handlers ([exn:fail? (λ (e)
                                 (printf "Error cargando ~a: ~a\n"
                                         image-name (exn-message e))
                                 #f)])
      (make-object bitmap% image-path)))

  (if (or (not bmp) (not (send bmp ok?)))
      (values "" 0)

      (let* ([w           (send bmp get-width)]
             [h           (send bmp get-height)]
             [pixel-bytes (make-bytes (* w h 4))])

        (send bmp get-argb-pixels 0 0 w h pixel-bytes)

        ;; 2. Ejecutar filtro midiendo tiempo real con precisión sub-ms.
        (define start-ms (current-inexact-milliseconds))
        (define final-bytes
          (cond
            [(equal? method-name "sequential")
             (cond
               [(equal? filter-name "negative")  (negative-sequential!  pixel-bytes)]
               [(equal? filter-name "grayscale") (grayscale-sequential! pixel-bytes)]
               [(equal? filter-name "sepia")     (sepia-sequential!     pixel-bytes)]
               [(equal? filter-name "edge")      (edge-sequential!      pixel-bytes w h)]
               [(equal? filter-name "gaussian")  (gaussian-sequential!  pixel-bytes w h)]
               [else (void)])
             pixel-bytes]

            [(equal? method-name "recursive")
             (cond
               [(equal? filter-name "negative")  (negative-recursive  pixel-bytes)]
               [(equal? filter-name "grayscale") (grayscale-recursive pixel-bytes)]
               [(equal? filter-name "sepia")     (sepia-recursive     pixel-bytes)]
               [(equal? filter-name "edge")      (edge-recursive      pixel-bytes w h)]
               [(equal? filter-name "gaussian")  (gaussian-recursive  pixel-bytes w h)]
               [else pixel-bytes])]

            [(equal? method-name "parallel")
             (cond
               [(equal? filter-name "negative")  (negative-parallel  pixel-bytes)]
               [(equal? filter-name "grayscale") (grayscale-parallel pixel-bytes)]
               [(equal? filter-name "sepia")     (sepia-parallel     pixel-bytes)]
               [(equal? filter-name "edge")      (edge-parallel      pixel-bytes w h)]
               [(equal? filter-name "gaussian")  (gaussian-parallel  pixel-bytes w h)]
               [else pixel-bytes])]

            [else pixel-bytes]))
        (define real-ms (- (current-inexact-milliseconds) start-ms))

        ;; 3. Reconstruir bitmap → PNG → Base64
        (define result-bmp (make-object bitmap% w h))
        (send result-bmp set-argb-pixels 0 0 w h final-bytes)

        (define out-port (open-output-bytes))
        (send result-bmp save-file out-port 'png)

        (define base64-str
          (bytes->string/utf-8
           (b64:base64-encode (get-output-bytes out-port))))

        (values base64-str real-ms))))
